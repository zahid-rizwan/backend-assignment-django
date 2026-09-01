from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from assets.models import Asset, CheckOut, Employee, OverdueNotice
from assets.tasks import flag_overdue_checkouts


class AssetApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username='tester', password='secret123')
        self.client.force_authenticate(user=self.user)

        self.employee = Employee.objects.create(
            employee_code='EMP-100',
            full_name='Test Employee',
            email='tester@example.com',
            is_active=True,
        )
        self.asset = Asset.objects.create(
            asset_tag='AST-100',
            name='Laptop',
            category=Asset.Category.LAPTOP,
            purchase_date='2024-01-01',
            status=Asset.Status.AVAILABLE,
        )

    def test_health_check(self):
        response = self.client.get(reverse('health-check'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data']['status'], 'ok')

    def test_checkout_limit_enforced(self):
        for index in range(3):
            asset = Asset.objects.create(
                asset_tag=f'AST-{101 + index}',
                name=f'Asset {index}',
                category=Asset.Category.CAMERA,
                purchase_date='2024-01-01',
                status=Asset.Status.AVAILABLE,
            )
            CheckOut.objects.create(
                asset=asset,
                employee=self.employee,
                due_at=timezone.now() + timedelta(days=7),
            )

        response = self.client.post(
            reverse('checkout-create'),
            {'asset_tag': self.asset.asset_tag, 'employee_code': self.employee.employee_code, 'due_at': (timezone.now() + timedelta(days=5)).isoformat()},
            format='json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'CHECKOUT_LIMIT_REACHED')

    def test_employee_summary_and_overdue_report(self):
        past_due = CheckOut.objects.create(
            asset=self.asset,
            employee=self.employee,
            due_at=timezone.now() - timedelta(days=2),
            returned_at=None,
        )

        second_asset = Asset.objects.create(
            asset_tag='AST-200',
            name='Sensor',
            category=Asset.Category.SENSOR,
            purchase_date='2024-01-01',
            status=Asset.Status.AVAILABLE,
        )
        returned_checkout = CheckOut.objects.create(
            asset=second_asset,
            employee=self.employee,
            due_at=timezone.now() - timedelta(days=10),
            returned_at=timezone.now() - timedelta(days=3),
        )

        summary_response = self.client.get(reverse('employee-summary', args=[self.employee.employee_code]))
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(summary_response.json()['data']['currently_held_count'], 1)
        self.assertEqual(summary_response.json()['data']['currently_overdue_count'], 1)

        overdue_response = self.client.get(reverse('overdue-report'))
        self.assertEqual(overdue_response.status_code, 200)
        self.assertEqual(overdue_response.json()['data']['count'], 1)
        self.assertEqual(overdue_response.json()['data']['results'][0]['asset_tag'], past_due.asset.asset_tag)

    def test_flag_overdue_checkouts_is_idempotent(self):
        due_checkout = CheckOut.objects.create(
            asset=self.asset,
            employee=self.employee,
            due_at=timezone.now() - timedelta(days=5),
            returned_at=None,
        )

        flag_overdue_checkouts()
        flag_overdue_checkouts()

        self.assertEqual(OverdueNotice.objects.filter(checkout=due_checkout).count(), 1)
