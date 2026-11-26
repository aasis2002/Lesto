from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('redirect/', views.role_redirect, name='role_redirect'),
    path('register/customer/', views.register_customer, name='register_customer'),
    path('register/technician/', views.register_technician, name='register_technician'),
    path('kyc/upload/', views.upload_kyc, name='upload_kyc'),
    path('kyc/secure-file/<uuid:doc_id>/<str:field_name>/', views.serve_kyc_document, name='serve_kyc_document'),
    path('notifications/', views.notifications_list, name='notifications'),
]
