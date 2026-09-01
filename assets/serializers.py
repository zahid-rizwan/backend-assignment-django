from rest_framework import serializers
from .models import Asset, Employee, CheckOut, OverdueNotice


class AssetSerializer(serializers.ModelSerializer):
    current_holder = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = [
            'id', 'asset_tag', 'name', 'category', 'status',
            'purchase_date', 'created_at', 'updated_at', 'current_holder',
        ]

    def get_current_holder(self, obj):
        open_checkout = obj.checkouts.filter(returned_at__isnull=True).select_related('employee').first()
        if not open_checkout:
            return None
        return {
            'employee_code': open_checkout.employee.employee_code,
            'full_name': open_checkout.employee.full_name,
        }


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['id', 'employee_code', 'full_name', 'email', 'is_active']


class CheckOutSerializer(serializers.ModelSerializer):
    class Meta:
        model = CheckOut
        fields = [
            'id', 'asset', 'employee', 'checked_out_at',
            'due_at', 'returned_at', 'condition_note',
        ]
        read_only_fields = ['checked_out_at', 'returned_at']


class CheckOutCreateSerializer(serializers.Serializer):
    asset_tag = serializers.CharField()
    employee_code = serializers.CharField()
    due_at = serializers.DateTimeField()


class ReturnSerializer(serializers.Serializer):
    condition_note = serializers.CharField(required=False, allow_blank=True, default='')
    needs_maintenance = serializers.BooleanField(required=False, default=False)