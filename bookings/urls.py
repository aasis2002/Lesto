from django.urls import path
from . import views

app_name = 'bookings'

urlpatterns = [
    path('book/whatsapp/<slug:service_slug>/', views.initiate_whatsapp_booking, name='initiate_whatsapp_booking'),
    path('booking/enquiry/<str:enquiry_id>/', views.booking_whatsapp_redirect, name='booking_whatsapp_redirect'),
    path('track/', views.track_booking_public, name='track_booking_public'),

    # Customer Portal
    path('customer/dashboard/', views.customer_dashboard, name='customer_dashboard'),
    path('customer/bookings/<str:enquiry_id>/', views.customer_booking_detail, name='customer_booking_detail'),
    path('customer/bookings/<str:enquiry_id>/cancel/', views.customer_cancel_booking, name='customer_cancel_booking'),
    path('customer/bookings/<str:enquiry_id>/review/', views.customer_submit_review, name='customer_submit_review'),
    path('customer/bookings/<str:enquiry_id>/complaint/', views.customer_submit_complaint, name='customer_submit_complaint'),
    path('customer/profile/', views.customer_profile_view, name='customer_profile'),
    path('customer/addresses/', views.customer_addresses, name='customer_addresses'),
    path('customer/payments/', views.customer_payments, name='customer_payments'),

    # Technician Portal
    path('technician/dashboard/', views.technician_dashboard, name='technician_dashboard'),
    path('technician/jobs/<str:enquiry_id>/', views.technician_job_detail, name='technician_job_detail'),
    path('technician/jobs/<str:enquiry_id>/respond/', views.technician_respond_job, name='technician_respond_job'),
    path('technician/jobs/<str:enquiry_id>/status/', views.technician_update_status, name='technician_update_status'),
    path('technician/jobs/<str:enquiry_id>/note/', views.technician_add_note, name='technician_add_note'),
    path('technician/jobs/<str:enquiry_id>/photo/', views.technician_upload_photo, name='technician_upload_photo'),
    path('technician/profile/', views.technician_profile_view, name='technician_profile'),
    path('technician/earnings/', views.technician_earnings, name='technician_earnings'),
    path('technician/id-card/', views.technician_id_card, name='technician_id_card'),
    path('booking/<str:enquiry_id>/invoice/', views.booking_invoice, name='booking_invoice'),
]
