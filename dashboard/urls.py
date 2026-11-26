from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('admin-panel/', views.overview, name='overview'),
    path('admin-panel/categories/', views.categories_manage, name='categories_manage'),
    path('admin-panel/services/', views.services_manage, name='services_manage'),
    path('admin-panel/bookings/', views.bookings_manage, name='bookings_manage'),
    path('admin-panel/bookings/<str:enquiry_id>/', views.booking_detail_admin, name='booking_detail_admin'),
    path('admin-panel/kanban/', views.kanban_board, name='kanban_board'),
    path('admin-panel/kanban/move/', views.kanban_move_status, name='kanban_move_status'),
    path('admin-panel/assign-jobs/', views.assign_jobs_queue, name='assign_jobs_queue'),
    path('admin-panel/customers/', views.customers_manage, name='customers_manage'),
    path('admin-panel/technicians/', views.technicians_manage, name='technicians_manage'),
    path('admin-panel/kyc/', views.kyc_queue, name='kyc_queue'),
    path('admin-panel/reviews/', views.reviews_manage, name='reviews_manage'),
    path('admin-panel/complaints/', views.complaints_manage, name='complaints_manage'),
    path('admin-panel/website/', views.website_manage, name='website_manage'),
    path('admin-panel/settings/', views.business_settings_view, name='business_settings'),
    path('admin-panel/admins/', views.admin_users_manage, name='admin_users_manage'),
    path('admin-panel/logs/', views.activity_logs, name='activity_logs'),
]
