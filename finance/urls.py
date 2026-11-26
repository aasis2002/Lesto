from django.urls import path
from . import views

app_name = 'finance'

urlpatterns = [
    path('admin-panel/finance/', views.financial_overview, name='financial_overview'),
    path('admin-panel/payments/', views.payments_list, name='payments_list'),
    path('admin-panel/commissions/', views.commissions_list, name='commissions_list'),
    path('admin-panel/payouts/', views.payouts_list, name='payouts_list'),
    path('admin-panel/expenses/', views.expenses_list, name='expenses_list'),
    path('admin-panel/reports/', views.reports_export, name='reports_export'),
]
