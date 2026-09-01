from datetime import timedelta

from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, generics, filters
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

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
    # ← same as above, leave unchanged


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

    open_count = CheckOut.objects.filter(employee=employee, returned_at__isnull=True).count()
    if open_count >= 3:
        return error_response("employee already has 3 open checkouts", code="CHECKOUT_LIMIT_REACHED", status=409) 

    try:
        with transaction.atomic():
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

    return success_response(CheckOutSerializer(checkout).data, status=201) 


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