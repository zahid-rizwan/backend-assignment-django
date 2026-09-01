# ANSWERS.md

## Part B — Diagnose three broken snippets

### Snippet 1 — overdue report view

**What's wrong with it**

There are a few separate problems stacked on top of each other here, not just one.

The obvious one first: it loops over `checkouts` and touches `c.asset.name` and `c.employee.full_name` for every row, but never calls `select_related`. Each of those attribute accesses is a fresh query, so for N checkouts you're firing off roughly 2N extra queries. It's a textbook N+1.

Less obvious, but arguably worse: the actual "is this overdue" filter (`if c.due_at < timezone.now()`) happens in the Python loop, not in the database query. So the initial `CheckOut.objects.filter(returned_at__isnull=True)` pulls in *every open checkout*, overdue or not, and then throws most of them away after loading them into memory. On a table with a few hundred thousand open checkouts, you're paying to load and instantiate all of them just to discard 90% in a Python `if`.

Same story with the sorting — `rows.sort(...)` happens after everything's already in a Python list, when `order_by()` would let Postgres do it as part of the same query, using an index if one exists.

Two smaller things: it uses `JsonResponse` instead of DRF's `Response`, so it doesn't get pagination or consistent error handling like the rest of the API does. And there's no pagination at all — if the overdue set is large, this just tries to serialize and return everything in one response.

**Why it doesn't show up in casual testing**

None of this actually gives you a *wrong* answer at small scale — it just does more work than it needs to. If you're testing with 15 checkouts in your dev database, the N+1 queries take microseconds each, the Python filtering and sorting are instant, and the response body is tiny. It genuinely looks fine. The bug only becomes visible once the table has thousands of overdue rows, at which point every one of these choices compounds into real latency — which is exactly the situation described (8-second queries timing out at 10).

**How I'd fix it**

Push everything into the query instead of the loop:

```python
from django.db.models import F, ExpressionWrapper, DurationField
from rest_framework.response import Response
from rest_framework.decorators import api_view

@api_view(['GET'])
def overdue_report(request):
    now = timezone.now()
    days_overdue_expr = ExpressionWrapper(now - F('due_at'), output_field=DurationField())

    checkouts = (
        CheckOut.objects
        .filter(returned_at__isnull=True, due_at__lt=now)
        .select_related('asset', 'employee')
        .annotate(days_overdue_duration=days_overdue_expr)
        .order_by('-days_overdue_duration')
    )

    rows = [
        {
            'asset': c.asset.name,
            'asset_tag': c.asset.asset_tag,
            'employee': c.employee.full_name,
            'days_overdue': c.days_overdue_duration.days,
        }
        for c in checkouts
    ]
    return Response({'count': len(rows), 'rows': rows})
```

The remaining loop is just building a plain dict from data that's already been fetched — it's not issuing new queries, so it's fine.

**What would've caught this before it shipped**

Honestly, a simple `assertNumQueries(1)` test around this view would have caught the N+1 immediately, at any dataset size — it doesn't need thousands of rows to fail, it fails the moment a second query fires. Tools like `django-silk` or `nplusone` would flag it in dev too. For the filtering/sorting issue specifically, you'd need a seeded dataset of a realistic size (thousands of rows, not a handful) run against the endpoint with basic timing — which is part of why the assignment has you build a seed command in the first place.

---

### Snippet 2 — check-out endpoint

**What's wrong with it**

This one's missing basically every safety net a checkout endpoint needs. There's no `transaction.atomic()`, so the checkout row and the asset status update aren't guaranteed to happen together — if something fails between the two, you can end up with a checkout that exists against an asset that's still marked available. There's no `select_for_update()` either, which means two requests arriving at nearly the same moment can both read `status == AVAILABLE` before either has written back `CHECKED_OUT`, and both go on to create a checkout for the same physical asset.

Then there's the input handling. `Asset.objects.get(...)` and `Employee.objects.get(...)` aren't wrapped in anything, so an unknown `asset_tag` or `employee_code` just raises `DoesNotExist`, which Django turns into a raw 500 instead of a clean 404. `request.data["due_at"]` is accessed directly with dict indexing, so a missing field is a `KeyError`, also a 500. There's no check that the employee is actually active, and no bounds check on `due_at` at all — you could check something out for ten years from now and nothing would stop you.

**Why it doesn't show up in casual testing**

Manual testing is sequential by nature — you send one request, look at the response, send the next. The race condition needs two requests landing within microseconds of each other on the same row, which just never happens when you're clicking through Postman by hand. And every manual test naturally uses a real asset tag, a real employee code, and a sensible due date, because that's what you're actually trying to test — so the missing validation and missing 404 handling never get exercised until someone (or some automated test) deliberately sends bad input or fires concurrent requests.

**How I'd fix it**

```python
from django.db import transaction
from django.shortcuts import get_object_or_404
from datetime import timedelta

@api_view(['POST'])
def check_out_asset(request):
    serializer = CheckOutCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    employee = get_object_or_404(Employee, employee_code=data['employee_code'])
    if not employee.is_active:
        return Response({'detail': 'employee is not active'}, status=400)

    now = timezone.now()
    if data['due_at'] <= now or data['due_at'] > now + timedelta(days=30):
        return Response({'detail': 'due_at out of range'}, status=400)

    if CheckOut.objects.filter(employee=employee, returned_at__isnull=True).count() >= 3:
        return Response({'detail': 'limit reached'}, status=409)

    try:
        with transaction.atomic():
            asset = Asset.objects.select_for_update().get(asset_tag=data['asset_tag'])
            if asset.status != Asset.Status.AVAILABLE:
                return Response({'detail': 'not available'}, status=409)
            checkout = CheckOut.objects.create(asset=asset, employee=employee, due_at=data['due_at'])
            asset.status = Asset.Status.CHECKED_OUT
            asset.save(update_fields=['status'])
    except Asset.DoesNotExist:
        return Response({'detail': 'asset not found'}, status=404)

    return Response({'id': checkout.id}, status=201)
```

**What would've caught this before it shipped**

The one that matters most here is a real concurrency test — spin up two threads (or use `pytest-django`'s transaction test support) hitting the same asset at the same time and assert only one checkout is ever created. That's the only kind of test that actually exercises the race condition; nothing sequential ever will. Beyond that, basic negative-path tests — unknown asset tag expecting 404, missing/invalid `due_at` expecting 400 — would catch the rest. And honestly, a review checklist habit of asking "does this endpoint read something and then write based on what it read?" is usually enough to flag the missing lock before it's even written.

---

### Snippet 3 — nightly notice task

**What's wrong with it**

The core problem is that this task isn't safe to retry. If it fails partway through — say it's created 500 `OverdueNotice` rows and then crashes — Celery will retry it from the top, reprocessing checkouts it already handled. If the `OverdueNotice` model has the unique constraint on `(checkout, notice_date)` from Part A, that retry blows up immediately with an `IntegrityError` on the first already-notified row, which means it never even reaches the *new* overdue checkouts that genuinely need a notice. Nothing in this code catches that or skips past it.

There's also `deliver_email.delay(c.employee, c)` — passing full model instances as Celery task arguments. Celery has to serialize whatever you hand it (usually to JSON), and a live ORM object either doesn't survive that or, if a looser serializer is configured, ends up passing a stale snapshot of the object into a worker that might run much later. The standard move is to pass IDs and let the task re-fetch fresh data itself.

And then there's scale: the loop iterates the queryset directly with no `.iterator()`, meaning all matching rows get loaded into memory as full model objects at once — fine for ten rows, not fine for the "tens of thousands" this task is explicitly meant to handle. `overdue.count()` at the very end is also a second, separate query, run right when the table is at its largest, just to report a number that could've been tracked while looping instead.

**Why it doesn't show up in casual testing**

A dev environment usually has a handful of overdue checkouts, and you basically never trigger a retry on purpose — so the idempotency bug just doesn't have a chance to fire. The memory and query-count issues are purely a function of row count, and dev data is never at production scale. And the Celery serialization risk depends entirely on how the broker's configured — plenty of local/test setups run tasks eagerly and skip serialization altogether, so the model-instance problem is invisible until it's running against a real broker in production.

**How I'd fix it**

```python
from django.db import IntegrityError

@shared_task
def send_overdue_notices():
    today = timezone.now().date()
    overdue_qs = (
        CheckOut.objects
        .filter(returned_at__isnull=True, due_at__lt=timezone.now())
        .only('id', 'employee_id')
        .iterator(chunk_size=500)
    )

    sent = 0
    for checkout in overdue_qs:
        try:
            OverdueNotice.objects.create(checkout_id=checkout.id, notice_date=today)
        except IntegrityError:
            continue  # already notified today — safe to skip on retry
        deliver_email.delay(checkout.employee_id, checkout.id)
        sent += 1

    return f"sent {sent} notices"
```

**What would've caught this before it shipped**

The most direct test is just running the task twice in a row against the same data and checking that no duplicate notices or duplicate emails happen — that targets the idempotency issue head-on regardless of scale. A lint rule or review habit around "never pass a model instance into `.delay()`" would catch the serialization risk. And for the scale problem specifically, there's really no substitute for testing against a seeded dataset that's actually large — tens of thousands of rows, not ten — before trusting this in production.
