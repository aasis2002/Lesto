from datetime import datetime, timedelta
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Avg, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from core.forms import AddressForm
from core.models import (
    Address, BusinessSettings, Notification, User, WhatsAppCommunicationLog,
)
from core.utils import build_whatsapp_url, notify_admins, notify_user, role_required
from finance.models import Payment, TechnicianCommission, TechnicianPayout
from services.models import Service
from .forms import ComplaintForm, JobUpdateForm, ReviewForm, WhatsAppBookingForm
from .models import (
    Booking, BookingStatusHistory, Complaint, JobAssignment, JobAttachment, JobUpdate, Review,
)


def initiate_whatsapp_booking(request, service_slug):
    service = get_object_or_404(Service, slug=service_slug, is_available=True, is_deleted=False)
    biz = BusinessSettings.get_solo()

    if request.method != 'POST':
        return redirect('services:service_detail', slug=service.slug)

    if biz.require_customer_verification_for_booking:
        if not request.user.is_authenticated:
            messages.warning(request, 'Please log in and verify your account before booking.')
            return redirect('core:login')
        cp = getattr(request.user, 'customer_profile', None)
        if not cp or cp.verification_status != 'approved':
            messages.warning(request, 'Your customer account must be KYC-verified before submitting a booking.')
            return redirect('core:upload_kyc')

    form = WhatsAppBookingForm(request.POST, request.FILES, service=service)
    if not form.is_valid():
        messages.error(request, 'Please check the booking form fields and try again.')
        return render(request, 'public/service_detail.html', {
            'service': service,
            'booking_form': form,
            'reviews': Review.objects.filter(service=service, is_visible=True),
            'related_services': Service.objects.filter(category=service.category, is_available=True).exclude(pk=service.pk)[:4],
            'included_items': [l.strip() for l in (service.whats_included or '').splitlines() if l.strip()],
        })

    cd = form.cleaned_data
    with transaction.atomic():
        booking = Booking.objects.create(
            customer=request.user if request.user.is_authenticated else None,
            customer_name=cd['customer_name'],
            customer_phone=cd['customer_phone'],
            customer_whatsapp=cd.get('customer_whatsapp') or cd['customer_phone'],
            category=service.category,
            subcategory=cd.get('subcategory') or service.subcategory,
            service=service,
            service_name_snapshot=service.name,
            description=cd['description'],
            preferred_date=cd['preferred_date'],
            preferred_time=cd['preferred_time'],
            address=cd['address'],
            city=cd.get('city') or (cd['service_area'].city if cd.get('service_area') else ''),
            service_area=cd.get('service_area'),
            estimated_price=service.effective_price,
            final_price=service.effective_price,
            status=Booking.STATUS_WHATSAPP_INITIATED,
        )

        BookingStatusHistory.objects.create(
            booking=booking,
            from_status='',
            to_status=Booking.STATUS_ENQUIRY_SUBMITTED,
            changed_by=request.user if request.user.is_authenticated else None,
            note='Booking enquiry saved in database.',
        )
        BookingStatusHistory.objects.create(
            booking=booking,
            from_status=Booking.STATUS_ENQUIRY_SUBMITTED,
            to_status=Booking.STATUS_WHATSAPP_INITIATED,
            changed_by=request.user if request.user.is_authenticated else None,
            note='Customer initiated WhatsApp Click-to-Chat booking.',
        )

        for f in request.FILES.getlist('photo'):
            JobAttachment.objects.create(
                booking=booking,
                uploaded_by=request.user if request.user.is_authenticated else None,
                stage='customer_enquiry',
                file=f,
                caption='Customer enquiry photo',
            )

        template = biz.default_booking_message
        message_text = template.format(
            enquiry_id=booking.enquiry_id,
            customer_name=booking.customer_name,
            service_name=booking.service_name_snapshot,
            category_name=service.category.name,
            address=booking.address,
            preferred_date=booking.preferred_date.strftime('%Y-%m-%d'),
            preferred_time=booking.preferred_time,
            description=booking.description,
        )
        wa_number = biz.booking_whatsapp_number or biz.primary_whatsapp_number
        wa_url = build_whatsapp_url(wa_number, message_text)
        booking.whatsapp_redirect_url = wa_url
        booking.save(update_fields=['whatsapp_redirect_url'])

        WhatsAppCommunicationLog.objects.create(
            booking=booking,
            sender_user=request.user if request.user.is_authenticated else None,
            recipient_phone=wa_number,
            direction='click_to_chat',
            message_body=message_text,
            template_name='default_booking_message',
            wa_link=wa_url,
            status='initiated',
        )

        notify_admins(
            f'New WhatsApp Enquiry {booking.enquiry_id}',
            f'{booking.customer_name} requested {booking.service_name_snapshot} for {booking.preferred_date}.',
            category='booking',
            link=f'/admin-panel/bookings/{booking.enquiry_id}/',
        )
        if request.user.is_authenticated:
            notify_user(
                request.user,
                f'Enquiry {booking.enquiry_id} Submitted',
                f'Your WhatsApp enquiry for {booking.service_name_snapshot} has been saved. Our team will confirm availability shortly.',
                category='booking',
                link=f'/customer/bookings/{booking.enquiry_id}/',
            )

    return redirect('bookings:booking_whatsapp_redirect', enquiry_id=booking.enquiry_id)


def booking_whatsapp_redirect(request, enquiry_id):
    booking = get_object_or_404(Booking, enquiry_id=enquiry_id)
    return render(request, 'public/whatsapp_redirect.html', {'booking': booking})


def track_booking_public(request):
    enquiry_id = request.GET.get('enquiry_id', '').strip().upper()
    phone = request.GET.get('phone', '').strip()
    booking = None
    error = None
    if enquiry_id:
        qs = Booking.objects.filter(enquiry_id=enquiry_id)
        if request.user.is_authenticated and (request.user.is_admin_user or qs.filter(customer=request.user).exists()):
            booking = qs.first()
        elif phone:
            booking = qs.filter(customer_phone__icontains=phone[-6:]).first()
        else:
            error = 'Please enter the mobile number used for this enquiry to view tracking details.'
        if not booking and not error:
            error = 'No matching booking enquiry found.'

    timeline_steps = [
        (Booking.STATUS_ENQUIRY_SUBMITTED, 'Enquiry Submitted'),
        (Booking.STATUS_WHATSAPP_INITIATED, 'WhatsApp Contact Initiated'),
        (Booking.STATUS_CONFIRMED, 'Booking Confirmed'),
        (Booking.STATUS_TECHNICIAN_ASSIGNED, 'Technician Assigned'),
        (Booking.STATUS_ON_THE_WAY, 'Technician On The Way'),
        (Booking.STATUS_WORK_STARTED, 'Work Started'),
        (Booking.STATUS_WORK_COMPLETED, 'Work Completed'),
        (Booking.STATUS_PAYMENT_PENDING, 'Payment Pending'),
        (Booking.STATUS_PAYMENT_COMPLETED, 'Payment Completed'),
        (Booking.STATUS_CLOSED, 'Booking Closed'),
    ]
    return render(request, 'public/track_booking.html', {
        'booking': booking,
        'enquiry_id': enquiry_id,
        'phone': phone,
        'error': error,
        'timeline_steps': timeline_steps,
    })


# ==================== CUSTOMER PORTAL ====================

@role_required(User.ROLE_CUSTOMER)
def customer_dashboard(request):
    bookings_qs = Booking.objects.filter(customer=request.user).select_related('service', 'category', 'assigned_technician')
    stats = {
        'total': bookings_qs.count(),
        'pending': bookings_qs.filter(status__in=[Booking.STATUS_ENQUIRY_SUBMITTED, Booking.STATUS_WHATSAPP_INITIATED]).count(),
        'confirmed': bookings_qs.filter(status=Booking.STATUS_CONFIRMED).count(),
        'active': bookings_qs.filter(status__in=[Booking.STATUS_TECHNICIAN_ASSIGNED, Booking.STATUS_ON_THE_WAY, Booking.STATUS_WORK_STARTED]).count(),
        'completed': bookings_qs.filter(status__in=[Booking.STATUS_WORK_COMPLETED, Booking.STATUS_PAYMENT_COMPLETED, Booking.STATUS_CLOSED]).count(),
        'cancelled': bookings_qs.filter(status=Booking.STATUS_CANCELLED).count(),
    }
    payments = Payment.objects.filter(customer=request.user).select_related('booking')[:5]
    addresses = Address.objects.filter(user=request.user)
    notifications = Notification.objects.filter(user=request.user)[:6]
    return render(request, 'customer/dashboard.html', {
        'stats': stats,
        'recent_bookings': bookings_qs[:15],
        'payments': payments,
        'addresses': addresses,
        'notifications': notifications,
    })


@role_required(User.ROLE_CUSTOMER)
def customer_booking_detail(request, enquiry_id):
    booking = get_object_or_404(
        Booking.objects.select_related('service', 'category', 'assigned_technician'),
        enquiry_id=enquiry_id,
        customer=request.user,
    )
    can_review = (
        booking.status in [Booking.STATUS_WORK_COMPLETED, Booking.STATUS_PAYMENT_COMPLETED, Booking.STATUS_CLOSED]
        and not hasattr(booking, 'review')
    )
    can_cancel = booking.status in [
        Booking.STATUS_ENQUIRY_SUBMITTED, Booking.STATUS_WHATSAPP_INITIATED, Booking.STATUS_CONFIRMED
    ]
    return render(request, 'customer/booking_detail.html', {
        'booking': booking,
        'can_review': can_review,
        'can_cancel': can_cancel,
        'review_form': ReviewForm(),
        'complaint_form': ComplaintForm(),
    })


@role_required(User.ROLE_CUSTOMER)
def customer_cancel_booking(request, enquiry_id):
    booking = get_object_or_404(Booking, enquiry_id=enquiry_id, customer=request.user)
    if request.method == 'POST':
        biz = BusinessSettings.get_solo()
        cancellable = [Booking.STATUS_ENQUIRY_SUBMITTED, Booking.STATUS_WHATSAPP_INITIATED, Booking.STATUS_CONFIRMED]
        if booking.status not in cancellable:
            messages.error(request, 'This booking can no longer be cancelled online. Please contact support.')
            return redirect('bookings:customer_booking_detail', enquiry_id=enquiry_id)

        scheduled_dt = timezone.make_aware(datetime.combine(booking.preferred_date, datetime.min.time()))
        if booking.status == Booking.STATUS_CONFIRMED and scheduled_dt - timezone.now() < timedelta(hours=biz.cancellation_window_hours):
            messages.error(
                request,
                f'Confirmed bookings must be cancelled at least {biz.cancellation_window_hours} hours before the scheduled date.'
            )
            return redirect('bookings:customer_booking_detail', enquiry_id=enquiry_id)

        reason = request.POST.get('reason', 'Cancelled by customer').strip() or 'Cancelled by customer'
        old_status = booking.status
        booking.status = Booking.STATUS_CANCELLED
        booking.cancellation_reason = reason
        booking.cancelled_by = request.user
        booking.save(update_fields=['status', 'cancellation_reason', 'cancelled_by', 'updated_at'])
        BookingStatusHistory.objects.create(
            booking=booking, from_status=old_status, to_status=Booking.STATUS_CANCELLED,
            changed_by=request.user, note=reason,
        )
        notify_admins(
            f'Booking Cancelled: {booking.enquiry_id}',
            f'{request.user.full_name} cancelled {booking.service_name_snapshot}. Reason: {reason}',
            category='booking',
            link=f'/admin-panel/bookings/{booking.enquiry_id}/',
        )
        messages.success(request, 'Booking has been cancelled.')
    return redirect('bookings:customer_booking_detail', enquiry_id=enquiry_id)


@role_required(User.ROLE_CUSTOMER)
def customer_submit_review(request, enquiry_id):
    booking = get_object_or_404(Booking, enquiry_id=enquiry_id, customer=request.user)
    if booking.status not in [Booking.STATUS_WORK_COMPLETED, Booking.STATUS_PAYMENT_COMPLETED, Booking.STATUS_CLOSED]:
        messages.error(request, 'Only completed bookings can be reviewed.')
        return redirect('bookings:customer_booking_detail', enquiry_id=enquiry_id)
    if hasattr(booking, 'review'):
        messages.info(request, 'You have already submitted a review for this booking.')
        return redirect('bookings:customer_booking_detail', enquiry_id=enquiry_id)

    form = ReviewForm(request.POST, request.FILES)
    if form.is_valid():
        review = form.save(commit=False)
        review.booking = booking
        review.customer = request.user
        review.technician = booking.assigned_technician
        review.service = booking.service
        review.save()
        if booking.assigned_technician and hasattr(booking.assigned_technician, 'technician_profile'):
            avg = Review.objects.filter(technician=booking.assigned_technician, is_visible=True).aggregate(
                a=Avg('technician_rating')
            )['a'] or 0
            tp = booking.assigned_technician.technician_profile
            tp.average_rating = round(avg, 2)
            tp.save(update_fields=['average_rating'])
        messages.success(request, 'Thank you for your review!')
    return redirect('bookings:customer_booking_detail', enquiry_id=enquiry_id)


@role_required(User.ROLE_CUSTOMER)
def customer_submit_complaint(request, enquiry_id):
    booking = get_object_or_404(Booking, enquiry_id=enquiry_id, customer=request.user)
    form = ComplaintForm(request.POST)
    if form.is_valid():
        complaint = form.save(commit=False)
        complaint.booking = booking
        complaint.customer = request.user
        complaint.save()
        notify_admins(
            f'New Customer Complaint ({booking.enquiry_id})',
            f'{request.user.full_name}: {complaint.subject}',
            category='complaint',
            link='/admin-panel/complaints/',
        )
        messages.success(request, 'Your complaint has been logged. Our support team will reach out shortly.')
    return redirect('bookings:customer_booking_detail', enquiry_id=enquiry_id)


@role_required(User.ROLE_CUSTOMER)
def customer_profile_view(request):
    cp = request.user.customer_profile
    if request.method == 'POST':
        request.user.full_name = request.POST.get('full_name', request.user.full_name).strip()
        request.user.email = request.POST.get('email', request.user.email).strip()
        request.user.whatsapp_number = request.POST.get('whatsapp_number', request.user.whatsapp_number).strip()
        if request.FILES.get('profile_photo'):
            request.user.profile_photo = request.FILES['profile_photo']
        request.user.save()
        cp.residential_address = request.POST.get('residential_address', cp.residential_address)
        cp.city = request.POST.get('city', cp.city)
        cp.district = request.POST.get('district', cp.district)
        cp.state = request.POST.get('state', cp.state)
        cp.postal_code = request.POST.get('postal_code', cp.postal_code)
        cp.save()
        messages.success(request, 'Profile updated successfully.')
        return redirect('bookings:customer_profile')
    return render(request, 'customer/profile.html', {'profile': cp})


@role_required(User.ROLE_CUSTOMER)
def customer_addresses(request):
    form = AddressForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        addr = form.save(commit=False)
        addr.user = request.user
        if addr.is_default:
            Address.objects.filter(user=request.user).update(is_default=False)
        addr.save()
        messages.success(request, 'Address saved.')
        return redirect('bookings:customer_addresses')
    addresses = Address.objects.filter(user=request.user)
    return render(request, 'customer/addresses.html', {'addresses': addresses, 'form': form})


@role_required(User.ROLE_CUSTOMER)
def customer_payments(request):
    payments = Payment.objects.filter(customer=request.user).select_related('booking')
    return render(request, 'customer/payments.html', {'payments': payments})


# ==================== TECHNICIAN PORTAL ====================

@role_required(User.ROLE_TECHNICIAN)
def technician_dashboard(request):
    tp = request.user.technician_profile
    jobs = Booking.objects.filter(assigned_technician=request.user).select_related('service', 'category', 'customer')
    commissions = TechnicianCommission.objects.filter(technician=request.user)
    total_earnings = commissions.aggregate(s=Sum('technician_amount'))['s'] or Decimal('0.00')
    paid_earnings = commissions.filter(is_paid_out=True).aggregate(s=Sum('technician_amount'))['s'] or Decimal('0.00')
    pending_payouts = total_earnings - paid_earnings

    stats = {
        'total': jobs.count(),
        'pending': jobs.filter(status=Booking.STATUS_TECHNICIAN_ASSIGNED).count(),
        'in_progress': jobs.filter(status__in=[Booking.STATUS_ON_THE_WAY, Booking.STATUS_WORK_STARTED]).count(),
        'completed': jobs.filter(status__in=[Booking.STATUS_WORK_COMPLETED, Booking.STATUS_PAYMENT_PENDING, Booking.STATUS_PAYMENT_COMPLETED, Booking.STATUS_CLOSED]).count(),
        'cancelled': jobs.filter(status=Booking.STATUS_CANCELLED).count(),
        'total_earnings': total_earnings,
        'paid_earnings': paid_earnings,
        'pending_payouts': pending_payouts,
        'rating': tp.average_rating,
    }
    return render(request, 'technician/dashboard.html', {
        'profile': tp,
        'stats': stats,
        'jobs': jobs[:20],
    })


@role_required(User.ROLE_TECHNICIAN)
def technician_job_detail(request, enquiry_id):
    booking = get_object_or_404(
        Booking.objects.select_related('service', 'category', 'customer'),
        enquiry_id=enquiry_id,
        assigned_technician=request.user,
    )
    latest_assignment = booking.assignments.filter(technician=request.user).first()
    customer_wa_url = build_whatsapp_url(
        booking.customer_whatsapp or booking.customer_phone,
        f"Hello {booking.customer_name}, I am {request.user.full_name} from LetsTo assigned to your booking {booking.enquiry_id} ({booking.service_name_snapshot})."
    )
    return render(request, 'technician/job_detail.html', {
        'booking': booking,
        'assignment': latest_assignment,
        'customer_wa_url': customer_wa_url,
        'note_form': JobUpdateForm(),
    })


@role_required(User.ROLE_TECHNICIAN)
def technician_respond_job(request, enquiry_id):
    booking = get_object_or_404(Booking, enquiry_id=enquiry_id, assigned_technician=request.user)
    assignment = booking.assignments.filter(technician=request.user, acceptance_status='pending').first()
    if request.method == 'POST' and assignment:
        decision = request.POST.get('decision')
        if decision == 'accept':
            assignment.acceptance_status = 'accepted'
            assignment.responded_at = timezone.now()
            assignment.save()
            notify_admins(
                f'Job Accepted: {booking.enquiry_id}',
                f'{request.user.full_name} accepted job {booking.enquiry_id}.',
                category='job',
                link=f'/admin-panel/bookings/{booking.enquiry_id}/',
            )
            messages.success(request, 'Job accepted!')
        elif decision == 'reject':
            reason = request.POST.get('reason', 'Technician unavailable').strip()
            assignment.acceptance_status = 'rejected'
            assignment.rejection_reason = reason
            assignment.responded_at = timezone.now()
            assignment.save()
            booking.assigned_technician = None
            booking.status = Booking.STATUS_CONFIRMED
            booking.save(update_fields=['assigned_technician', 'status', 'updated_at'])
            BookingStatusHistory.objects.create(
                booking=booking, from_status=Booking.STATUS_TECHNICIAN_ASSIGNED,
                to_status=Booking.STATUS_CONFIRMED, changed_by=request.user,
                note=f'Technician rejected assignment: {reason}',
            )
            notify_admins(
                f'Job Rejected by Technician: {booking.enquiry_id}',
                f'{request.user.full_name} rejected {booking.enquiry_id}. Reason: {reason}',
                category='job',
                link=f'/admin-panel/bookings/{booking.enquiry_id}/',
            )
            messages.warning(request, 'Job rejected and returned to dispatch queue.')
            return redirect('bookings:technician_dashboard')
    return redirect('bookings:technician_job_detail', enquiry_id=enquiry_id)


@role_required(User.ROLE_TECHNICIAN)
def technician_update_status(request, enquiry_id):
    booking = get_object_or_404(Booking, enquiry_id=enquiry_id, assigned_technician=request.user)
    allowed_next = {
        Booking.STATUS_TECHNICIAN_ASSIGNED: [Booking.STATUS_ON_THE_WAY],
        Booking.STATUS_ON_THE_WAY: [Booking.STATUS_WORK_STARTED],
        Booking.STATUS_WORK_STARTED: [Booking.STATUS_WORK_COMPLETED],
    }
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in allowed_next.get(booking.status, []):
            old_status = booking.status
            booking.status = new_status
            if new_status == Booking.STATUS_WORK_COMPLETED:
                booking.completed_at = timezone.now()
            booking.save()
            BookingStatusHistory.objects.create(
                booking=booking, from_status=old_status, to_status=new_status,
                changed_by=request.user, note=f'Updated by technician {request.user.full_name}',
            )
            if booking.customer:
                notify_user(
                    booking.customer,
                    f'Booking {booking.enquiry_id} Update',
                    f'Your service status is now: {booking.get_status_display()}.',
                    category='booking',
                    link=f'/customer/bookings/{booking.enquiry_id}/',
                )
            messages.success(request, f'Job status updated to {booking.get_status_display()}.')
        else:
            messages.error(request, 'Invalid status transition.')
    return redirect('bookings:technician_job_detail', enquiry_id=enquiry_id)


@role_required(User.ROLE_TECHNICIAN)
def technician_add_note(request, enquiry_id):
    booking = get_object_or_404(Booking, enquiry_id=enquiry_id, assigned_technician=request.user)
    form = JobUpdateForm(request.POST)
    if form.is_valid():
        upd = form.save(commit=False)
        upd.booking = booking
        upd.author = request.user
        upd.save()
        if upd.requested_material_amount and upd.requested_material_amount > 0:
            notify_admins(
                f'Material Charge Requested: {booking.enquiry_id}',
                f'{request.user.full_name} requested additional material charge of {upd.requested_material_amount}.',
                category='finance',
                link=f'/admin-panel/bookings/{booking.enquiry_id}/',
            )
        messages.success(request, 'Job note saved.')
    return redirect('bookings:technician_job_detail', enquiry_id=enquiry_id)


@role_required(User.ROLE_TECHNICIAN)
def technician_upload_photo(request, enquiry_id):
    booking = get_object_or_404(Booking, enquiry_id=enquiry_id, assigned_technician=request.user)
    if request.method == 'POST' and request.FILES.get('file'):
        stage = request.POST.get('stage', 'before_work')
        if stage not in ('before_work', 'after_work'):
            stage = 'before_work'
        JobAttachment.objects.create(
            booking=booking,
            uploaded_by=request.user,
            stage=stage,
            file=request.FILES['file'],
            caption=request.POST.get('caption', ''),
        )
        messages.success(request, 'Photo uploaded successfully.')
    return redirect('bookings:technician_job_detail', enquiry_id=enquiry_id)


@role_required(User.ROLE_TECHNICIAN)
def technician_profile_view(request):
    tp = request.user.technician_profile
    if request.method == 'POST':
        tp.is_available = request.POST.get('is_available') == 'on'
        tp.live_gps_consent = request.POST.get('live_gps_consent') == 'on'
        tp.skills_summary = request.POST.get('skills_summary', tp.skills_summary)
        tp.save()
        messages.success(request, 'Availability & profile preferences updated.')
        return redirect('bookings:technician_profile')
    return render(request, 'technician/profile.html', {'profile': tp})


@role_required(User.ROLE_TECHNICIAN)
def technician_earnings(request):
    commissions = TechnicianCommission.objects.filter(technician=request.user).select_related('booking')
    payouts = TechnicianPayout.objects.filter(technician=request.user)
    total_earned = commissions.aggregate(s=Sum('technician_amount'))['s'] or Decimal('0.00')
    total_paid = payouts.filter(status='paid').aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    return render(request, 'technician/earnings.html', {
        'commissions': commissions,
        'payouts': payouts,
        'total_earned': total_earned,
        'total_paid': total_paid,
        'pending_balance': total_earned - total_paid,
    })


@login_required
def booking_invoice(request, enquiry_id):
    booking = get_object_or_404(
        Booking.objects.select_related('category', 'service', 'assigned_technician'),
        enquiry_id=enquiry_id,
    )
    if not (
        request.user.is_admin_user
        or booking.customer_id == request.user.id
        or booking.assigned_technician_id == request.user.id
    ):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('You cannot view this invoice.')
    return render(request, 'bookings/invoice.html', {'booking': booking})


@role_required(User.ROLE_TECHNICIAN)
def technician_id_card(request):
    return render(request, 'technician/id_card.html', {'profile': request.user.technician_profile})
