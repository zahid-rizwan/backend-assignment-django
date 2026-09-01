from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from assets.models import Asset, Employee, CheckOut


class Command(BaseCommand):
    help = "Seeds the database with demo data for manual testing and review."

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()

        assets_data = [
            ('CAM-0001', 'Canon EOS R6', Asset.Category.CAMERA, '2024-01-15'),
            ('CAM-0002', 'Sony A7 IV', Asset.Category.CAMERA, '2024-02-10'),
            ('LAP-0001', 'MacBook Pro 16"', Asset.Category.LAPTOP, '2023-11-01'),
            ('LAP-0002', 'Dell XPS 15', Asset.Category.LAPTOP, '2024-03-05'),
            ('SEN-0001', 'Temperature Sensor T1', Asset.Category.SENSOR, '2024-01-20'),
            ('SEN-0002', 'Humidity Sensor H1', Asset.Category.SENSOR, '2024-01-20'),
            ('VEH-0001', 'Field Van #1', Asset.Category.VEHICLE, '2022-06-01'),
            ('VEH-0002', 'Field Van #2', Asset.Category.VEHICLE, '2022-07-15'),
        ]
        assets = {}
        for tag, name, category, purchase_date in assets_data:
            asset, _ = Asset.objects.update_or_create(
                asset_tag=tag,
                defaults={
                    'name': name,
                    'category': category,
                    'purchase_date': purchase_date,
                },
            )
            assets[tag] = asset

        employees_data = [
            ('EMP-001', 'Asha Verma', 'asha.verma@example.com', True),
            ('EMP-002', 'Ravi Kumar', 'ravi.kumar@example.com', True),
            ('EMP-003', 'Neha Singh', 'neha.singh@example.com', True),
            ('EMP-004', 'Old Employee', 'old.employee@example.com', False),
        ]
        employees = {}
        for code, name, email, is_active in employees_data:
            employee, _ = Employee.objects.update_or_create(
                employee_code=code,
                defaults={'full_name': name, 'email': email, 'is_active': is_active},
            )
            employees[code] = employee

        CheckOut.objects.filter(
            asset__asset_tag__in=assets.keys(),
            employee__employee_code__in=employees.keys(),
        ).delete()
        for asset in assets.values():
            asset.status = Asset.Status.AVAILABLE
            asset.save(update_fields=['status'])

        def make_checkout(asset_tag, emp_code, checked_out_days_ago, due_days_from_checkout,
                           returned_days_ago=None, mark_asset_status=None):
            checked_out_at = now - timedelta(days=checked_out_days_ago)
            due_at = checked_out_at + timedelta(days=due_days_from_checkout)
            returned_at = (now - timedelta(days=returned_days_ago)) if returned_days_ago is not None else None

            checkout = CheckOut.objects.create(
                asset=assets[asset_tag],
                employee=employees[emp_code],
                due_at=due_at,
                returned_at=returned_at,
            )
            # auto_now_add fixes checked_out_at to "now" on create — override it directly after
            CheckOut.objects.filter(pk=checkout.pk).update(checked_out_at=checked_out_at)

            asset = assets[asset_tag]
            if mark_asset_status is not None:
                asset.status = mark_asset_status
                asset.save(update_fields=['status'])
            return checkout

        make_checkout('CAM-0001', 'EMP-001', checked_out_days_ago=10, due_days_from_checkout=3,
                       mark_asset_status=Asset.Status.CHECKED_OUT)
        make_checkout('LAP-0001', 'EMP-002', checked_out_days_ago=15, due_days_from_checkout=5,
                       mark_asset_status=Asset.Status.CHECKED_OUT)

        make_checkout('SEN-0001', 'EMP-001', checked_out_days_ago=20, due_days_from_checkout=10,
                       returned_days_ago=12)
        make_checkout('VEH-0001', 'EMP-003', checked_out_days_ago=30, due_days_from_checkout=7,
                       returned_days_ago=25)

        make_checkout('CAM-0002', 'EMP-002', checked_out_days_ago=25, due_days_from_checkout=5,
                       returned_days_ago=10)

        make_checkout('LAP-0002', 'EMP-003', checked_out_days_ago=1, due_days_from_checkout=14,
                       mark_asset_status=Asset.Status.CHECKED_OUT)

        self.stdout.write(self.style.SUCCESS(
            "Seeded 8 assets, 4 employees (1 inactive), and 6 checkouts "
            "(2 overdue, 2 returned on time, 1 returned late, 1 open not-yet-due)."
        ))