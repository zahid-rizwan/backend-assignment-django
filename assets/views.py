from datetime import timedelta

from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, generics, filters
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend


from django.db.models import Count, Avg, Q, F, DurationField, ExpressionWrapper
from .models import Asset, Employee, CheckOut

from .models import Asset, Employee, CheckOut
from .serializers import (
    AssetSerializer, EmployeeSerializer, CheckOutSerializer,
    CheckOutCreateSerializer, ReturnSerializer,
)

from core.api_utils import success_response, error_response


class AssetListCreateView(generics.ListCreateAPIView):
    queryset = Asset.objects.all()
    serializer_class = AssetSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['status', 'category']
    search_fields = ['name', 'asset_tag']
    # ← LEAVE THIS CLASS UNCHANGED — generic views handle their own
    #    response format via DRF internals; wrapping them requires
    #    overriding list()/create(), which is extra work for one field.
    #    Skip unless you have time to spare.


class AssetDetailView(generics.RetrieveAPIView):
    queryset = Asset.objects.all()
    serializer_class = AssetSerializer


@api_view(['POST'])
def check_out_asset(request):
    serializer = CheckOutCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    employee = get_object_or_404(Employee, employee_code=data['employee_code'])

    if not employee.is_active:
        return error_response("employee is not active", code="EMPLOYEE_INACTIVE", status=400)

    now = timezone.now()
    if data['due_at'] <= now or data['due_at'] > now + timedelta(days=30):
        return error_response(                                                                
            "due_at must be in the future and within 30 days",
            code="INVALID_DUE_DATE", status=400,
        )

    try:
        with transaction.atomic():
            employee = Employee.objects.select_for_update().get(pk=employee.pk)

            open_count = CheckOut.objects.filter(employee=employee, returned_at__isnull=True).count()
            if open_count >= 3:
                return error_response("employee already has 3 open checkouts", code="CHECKOUT_LIMIT_REACHED", status=409)

            asset = Asset.objects.select_for_update().get(asset_tag=data['asset_tag'])

            if asset.status != Asset.Status.AVAILABLE:
                return error_response("asset is not available", code="ASSET_NOT_AVAILABLE", status=409)

            checkout = CheckOut.objects.create(
                asset=asset,
                employee=employee,
                due_at=data['due_at'],
            )
            asset.status = Asset.Status.CHECKED_OUT
            asset.save(update_fields=['status', 'updated_at'])
    except Asset.DoesNotExist:
        return error_response("asset not found", code="ASSET_NOT_FOUND", status=404)


@api_view(['POST'])
def return_asset(request, pk):
    serializer = ReturnSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    checkout = get_object_or_404(CheckOut, pk=pk)

    if checkout.returned_at is not None:
        return error_response("already returned", code="ALREADY_RETURNED", status=409)   

    with transaction.atomic():
        checkout.returned_at = timezone.now()
        checkout.condition_note = data['condition_note']
        checkout.save(update_fields=['returned_at', 'condition_note'])

        asset = checkout.asset
        asset.status = Asset.Status.MAINTENANCE if data['needs_maintenance'] else Asset.Status.AVAILABLE
        asset.save(update_fields=['status', 'updated_at'])

    return success_response(CheckOutSerializer(checkout).data, status=200)



@api_view(['GET'])
def employee_summary(request, employee_code):
    employee = get_object_or_404(Employee, employee_code=employee_code)
    now = timezone.now()

    duration_expr = ExpressionWrapper(
        F('checkouts__returned_at') - F('checkouts__checked_out_at'),
        output_field=DurationField(),
    )

    stats = Employee.objects.filter(pk=employee.pk).aggregate(
        lifetime_checkout_count=Count('checkouts'),
        currently_held_count=Count(
            'checkouts', filter=Q(checkouts__returned_at__isnull=True)
        ),
        currently_overdue_count=Count(
            'checkouts',
            filter=Q(checkouts__returned_at__isnull=True, checkouts__due_at__lt=now),
        ),
        mean_hold_duration=Avg(
            duration_expr, filter=Q(checkouts__returned_at__isnull=False)
        ),
    )

    mean_days = None
    if stats['mean_hold_duration'] is not None:
        mean_days = round(stats['mean_hold_duration'].total_seconds() / 86400, 2)

    return success_response({
        'employee_code': employee.employee_code,
        'full_name': employee.full_name,
        'lifetime_checkout_count': stats['lifetime_checkout_count'],
        'currently_held_count': stats['currently_held_count'],
        'currently_overdue_count': stats['currently_overdue_count'],
        'mean_hold_duration_days': mean_days,
    })


@api_view(['GET'])
def overdue_report(request):
    now = timezone.now()
    days_overdue_expr = ExpressionWrapper(
        now - F('due_at'), output_field=DurationField()
    )

    checkouts = (
        CheckOut.objects
        .filter(returned_at__isnull=True, due_at__lt=now)
        .select_related('asset', 'employee')
        .annotate(days_overdue_duration=days_overdue_expr)
        .order_by('-days_overdue_duration')
    )

    rows = [
        {
            'asset_name': c.asset.name,
            'asset_tag': c.asset.asset_tag,
            'employee_code': c.employee.employee_code,
            'employee_name': c.employee.full_name,
            'days_overdue': c.days_overdue_duration.days,
        }
        for c in checkouts
    ]

    return success_response({'count': len(rows), 'results': rows})