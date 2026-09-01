from datetime import timedelta

from celery import shared_task
from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone

from .models import CheckOut, OverdueNotice


@shared_task(bind=True, default_retry_delay=30, max_retries=3)
def flag_overdue_checkouts(self):
    now = timezone.now()
    cutoff = now - timedelta(days=1)
    overdue_qs = (
        CheckOut.objects
        .filter(returned_at__isnull=True, due_at__lt=now)
        .filter(Q(notices__isnull=True) | Q(notices__notice_date__lt=cutoff.date()))
        .distinct()
        .select_related('employee', 'asset')
    )

    created = 0
    for checkout in overdue_qs:
        notice_date = now.date()
        try:
            OverdueNotice.objects.create(checkout=checkout, notice_date=notice_date)
        except IntegrityError:
            continue
        created += 1

    return {'created': created, 'checked': overdue_qs.count()}
