from django.urls import path
from . import views

urlpatterns = [
    path('assets/', views.AssetListCreateView.as_view(), name='asset-list-create'),
    path('assets/<int:pk>/', views.AssetDetailView.as_view(), name='asset-detail'),
    path('checkouts/', views.check_out_asset, name='checkout-create'),
    path('checkouts/<int:pk>/return/', views.return_asset, name='checkout-return'),
]