from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.health_check, name='health-check'),
    path('health-check/', views.health_check, name='health-check-alias'),
    path('assets/', views.AssetListCreateView.as_view(), name='asset-list-create'),
    path('assets/<int:pk>/', views.AssetDetailView.as_view(), name='asset-detail'),
    path('checkouts/', views.check_out_asset, name='checkout-create'),
    path('checkouts/<int:pk>/return/', views.return_asset, name='checkout-return'),
    path('employees/<str:employee_code>/summary/', views.employee_summary, name='employee-summary'),
    path('reports/overdue/', views.overdue_report, name='overdue-report'),
]