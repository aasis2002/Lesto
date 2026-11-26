import csv
import json
from datetime import timedelta
from decimal import Decimal
from django.contrib import messages
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from core.models import (
    AdminActivityLog, AdminProfile, BusinessSettings, CustomerProfile,
    DocumentAccessLog, IdentityDocument, Notification, RolePermission,
    TechnicianProfile, User, Verification, WebsiteSettings, WhatsAppCommunicationLog,
)
from core.utils import admin_permission_required, build_whatsapp_url, log_admin_activity, notify_user
from bookings.models import (
    Booking, BookingStatusHistory, Complaint, JobAssignment, Review,
)
from finance.models import Expense, Payment, TechnicianCommission, TechnicianPayout
from finance.services import compute_financial_summary
from services.models import Service, ServiceArea, ServiceCategory, ServiceSubcategory


@admin_permission_required()
def overview(request):
    start_date = request.GET.get('start_date') or ''
    end_date = request.GET.get('end_date') or ''

    fin = compute_financial_summary(start_date or None, end_date or None)
    bookings_qs = Booking.objects.all()
    if start_date:
        bookings_qs = bookings_qs.filter(created_at__date__gte=start_date)
    if end_date:
        bookings_qs = bookings_qs.filter(created_at__date__lte=end_date)

    kpis = {
        'total_revenue': fin['net_revenue'],
        'total_expenses': fin['total_expenses'],
        'net_profit': fin['net_profit'],
        'total_bookings': bookings_qs.count(),
        'pending_bookings': bookings_qs.filter(status__in=[Booking.STATUS_ENQUIRY_SUBMITTED, Booking.STATUS_WHATSAPP_INITIATED]).count(),
        'active_jobs': bookings_qs.filter(status__in=[Booking.STATUS_CONFIRMED, Booking.STATUS_TECHNICIAN_ASSIGNED, Booking.STATUS_ON_THE_WAY, Booking.STATUS_WORK_STARTED]).count(),
        'completed_jobs': bookings_qs.filter(status__in=[Booking.STATUS_WORK_COMPLETED, Booking.STATUS_PAYMENT_COMPLETED, Booking.STATUS_CLOSED]).count(),
        'cancelled_jobs': bookings_qs.filter(status=Booking.STATUS_CANCELLED).count(),
        'total_customers': User.objects.filter(role=User.ROLE_CUSTOMER).count(),
        'total_technicians': User.objects.filter(role=User.ROLE_TECHNICIAN).count(),
        'pending_tech_approvals': TechnicianProfile.objects.filter(verification_status__in=['pending_review', 'under_verification']).count(),
        'pending_customer_verifications': CustomerProfile.objects.filter(verification_status__in=['pending_review', 'under_verification']).count(),
        'pending_payments': fin['pending_payments'],
        'outstanding_payouts': fin['outstanding_payouts'],
    }

    # Chart data (100% real DB aggregations)
    daily_rev = list(
        Payment.objects.filter(status='paid')
        .annotate(day=TruncDate('paid_at'))
        .values('day')
        .annotate(total=Sum('amount'))
        .order_by('day')[:30]
    )
    monthly_rev = list(
        Payment.objects.filter(status='paid')
        .annotate(month=TruncMonth('paid_at'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')[:12]
    )
    cat_perf = list(
        Booking.objects.values('category__name')
        .annotate(count=Count('id'), revenue=Sum('final_price'))
        .order_by('-count')[:8]
    )
    popular_services = list(
        Booking.objects.values('service_name_snapshot')
        .annotate(count=Count('id'))
        .order_by('-count')[:8]
    )
    payment_methods = list(
        Payment.objects.filter(status='paid')
        .values('method')
        .annotate(total=Sum('amount'), count=Count('id'))
    )
    geo_demand = list(
        Booking.objects.exclude(city='')
        .values('city')
        .annotate(count=Count('id'))
        .order_by('-count')[:8]
    )
    tech_perf = list(
        TechnicianProfile.objects.filter(verification_status='approved')
        .select_related('user')
        .annotate(jobs_done=Count('user__assigned_bookings', filter=Q(user__assigned_bookings__status__in=[Booking.STATUS_WORK_COMPLETED, Booking.STATUS_PAYMENT_COMPLETED, Booking.STATUS_CLOSED])))
        .order_by('-jobs_done')[:6]
    )

    chart_payload = {
        'daily_labels': [d['day'].strftime('%b %d') for d in daily_rev if d['day']],
        'daily_values': [float(d['total'] or 0) for d in daily_rev if d['day']],
        'monthly_labels': [m['month'].strftime('%b %Y') for m in monthly_rev if m['month']],
        'monthly_values': [float(m['total'] or 0) for m in monthly_rev if m['month']],
        'cat_labels': [c['category__name'] or 'Other' for c in cat_perf],
        'cat_counts': [c['count'] for c in cat_perf],
        'cat_revenue': [float(c['revenue'] or 0) for c in cat_perf],
        'pop_labels': [p['service_name_snapshot'] for p in popular_services],
        'pop_counts': [p['count'] for p in popular_services],
        'pm_labels': [p['method'].replace('_', ' ').title() for p in payment_methods],
        'pm_values': [float(p['total'] or 0) for p in payment_methods],
        'geo_labels': [g['city'] for g in geo_demand],
        'geo_counts': [g['count'] for g in geo_demand],
        'tech_labels': [t.full_legal_name for t in tech_perf],
        'tech_jobs': [t.jobs_done for t in tech_perf],
        'rev_vs_exp': [float(fin['net_revenue']), float(fin['total_expenses']), float(fin['platform_commission'])],
        'completion_vs_cancel': [kpis['completed_jobs'], kpis['active_jobs'], kpis['pending_bookings'], kpis['cancelled_jobs']],
    }

    recent_bookings = Booking.objects.select_related('category', 'assigned_technician')[:8]
    return render(request, 'admin_panel/overview.html', {
        'kpis': kpis,
        'chart_json': json.dumps(chart_payload),
        'recent_bookings': recent_bookings,
        'start_date': start_date,
        'end_date': end_date,
    })


# ==================== SERVICE CATEGORIES & SERVICES ====================

@admin_permission_required('can_manage_services')
def categories_manage(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create_category':
            cat = ServiceCategory.objects.create(
                name=request.POST.get('name', '').strip(),
                icon_name=request.POST.get('icon_name', 'wrench').strip() or 'wrench',
                description=request.POST.get('description', ''),
                display_order=int(request.POST.get('display_order') or 0),
                image=request.FILES.get('image'),
                is_active=True,
            )
            log_admin_activity(request.user, 'Created service category', 'ServiceCategory', cat.pk, cat.name, request)
            messages.success(request, f'Category "{cat.name}" created.')
        elif action == 'edit_category':
            cat = get_object_or_404(ServiceCategory, pk=request.POST.get('category_id'))
            cat.name = request.POST.get('name', cat.name).strip()
            cat.icon_name = request.POST.get('icon_name', cat.icon_name).strip()
            cat.description = request.POST.get('description', cat.description)
            cat.is_active = request.POST.get('is_active') == 'on'
            if request.FILES.get('image'):
                cat.image = request.FILES['image']
            cat.save()
            messages.success(request, f'Category "{cat.name}" updated.')
        elif action == 'delete_category':
            cat = get_object_or_404(ServiceCategory, pk=request.POST.get('category_id'))
            cat.is_deleted = True
            cat.is_active = False
            cat.save(update_fields=['is_deleted', 'is_active'])
            messages.info(request, f'Category "{cat.name}" deleted.')
        elif action == 'create_subcategory':
            cat = get_object_or_404(ServiceCategory, pk=request.POST.get('category_id'))
            sub = ServiceSubcategory.objects.create(
                category=cat,
                name=request.POST.get('name', '').strip(),
                description=request.POST.get('description', ''),
            )
            messages.success(request, f'Subcategory "{sub.name}" added to {cat.name}.')
        elif action == 'create_area':
            ServiceArea.objects.get_or_create(
                name=request.POST.get('name', '').strip(),
                city=request.POST.get('city', '').strip(),
                defaults={'district': request.POST.get('district', '').strip()}
            )
            messages.success(request, 'Service area saved.')
        return redirect('dashboard:categories_manage')

    categories = ServiceCategory.objects.filter(is_deleted=False).prefetch_related('subcategories')
    areas = ServiceArea.objects.all()
    return render(request, 'admin_panel/categories_manage.html', {'categories': categories, 'areas': areas})


@admin_permission_required('can_manage_services')
def services_manage(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action in ('create', 'edit'):
            if action == 'edit':
                srv = get_object_or_404(Service, pk=request.POST.get('service_id'))
            else:
                srv = Service()
            srv.category = get_object_or_404(ServiceCategory, pk=request.POST.get('category_id'))
            sub_id = request.POST.get('subcategory_id')
            srv.subcategory = ServiceSubcategory.objects.filter(pk=sub_id).first() if sub_id else None
            srv.name = request.POST.get('name', '').strip()
            srv.short_description = request.POST.get('short_description', '').strip()
            srv.description = request.POST.get('description', '').strip()
            srv.whats_included = request.POST.get('whats_included', '')
            srv.base_price = Decimal(request.POST.get('base_price') or 0)
            promo = request.POST.get('promo_price', '').strip()
            srv.promo_price = Decimal(promo) if promo else None
            srv.estimated_duration = request.POST.get('estimated_duration', '1 - 2 Hours').strip()
            comm = request.POST.get('technician_commission_rate', '').strip()
            srv.technician_commission_rate = Decimal(comm) if comm else None
            srv.is_featured = request.POST.get('is_featured') == 'on'
            srv.is_popular = request.POST.get('is_popular') == 'on'
            srv.is_available = request.POST.get('is_available') == 'on'
            if request.FILES.get('image'):
                srv.image = request.FILES['image']
            srv.save()
            area_ids = request.POST.getlist('service_areas')
            if area_ids:
                srv.service_areas.set(area_ids)
            log_admin_activity(request.user, f'{action.title()}d service', 'Service', srv.pk, srv.name, request)
            messages.success(request, f'Service "{srv.name}" saved.')
        elif action == 'toggle_availability':
            srv = get_object_or_404(Service, pk=request.POST.get('service_id'))
            srv.is_available = not srv.is_available
            srv.save(update_fields=['is_available'])
            messages.info(request, f'"{srv.name}" availability updated.')
        elif action == 'delete':
            srv = get_object_or_404(Service, pk=request.POST.get('service_id'))
            srv.is_deleted = True
            srv.is_available = False
            srv.save(update_fields=['is_deleted', 'is_available'])
            messages.info(request, f'Service "{srv.name}" removed.')
        return redirect('dashboard:services_manage')

    services = Service.objects.filter(is_deleted=False).select_related('category', 'subcategory')
    categories = ServiceCategory.objects.filter(is_deleted=False)
    subcategories = ServiceSubcategory.objects.filter(is_active=True)
    areas = ServiceArea.objects.filter(is_active=True)
    return render(request, 'admin_panel/services_manage.html', {
        'services': services,
        'categories': categories,
        'subcategories': subcategories,
        'areas': areas,
    })


# ==================== BOOKINGS & KANBAN ====================

@admin_permission_required('can_manage_bookings')
def bookings_manage(request):
    qs = Booking.objects.select_related('category', 'service', 'customer', 'assigned_technician')
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    cat_id = request.GET.get('category', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    if q:
        qs = qs.filter(
            Q(enquiry_id__icontains=q)
            | Q(customer_name__icontains=q)
            | Q(customer_phone__icontains=q)
            | Q(service_name_snapshot__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if cat_id.isdigit():
        qs = qs.filter(category_id=int(cat_id))
    if date_from:
        qs = qs.filter(preferred_date__gte=date_from)
    if date_to:
        qs = qs.filter(preferred_date__lte=date_to)

    return render(request, 'admin_panel/bookings_manage.html', {
        'bookings': qs[:100],
        'status_choices': Booking.STATUS_CHOICES,
        'categories': ServiceCategory.objects.filter(is_deleted=False),
        'filters': {'q': q, 'status': status, 'category': cat_id, 'date_from': date_from, 'date_to': date_to},
    })


@admin_permission_required('can_manage_bookings')
def booking_detail_admin(request, enquiry_id):
    booking = get_object_or_404(
        Booking.objects.select_related('category', 'subcategory', 'service', 'customer', 'assigned_technician'),
        enquiry_id=enquiry_id,
    )
    verified_techs = User.objects.filter(
        role=User.ROLE_TECHNICIAN,
        is_suspended=False,
        technician_profile__verification_status='approved',
    ).select_related('technician_profile')
    biz = BusinessSettings.get_solo()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_status':
            new_status = request.POST.get('status')
            note = request.POST.get('note', '').strip()
            if new_status in dict(Booking.STATUS_CHOICES):
                old = booking.status
                booking.status = new_status
                if new_status == Booking.STATUS_WORK_COMPLETED and not booking.completed_at:
                    booking.completed_at = timezone.now()
                booking.save()
                BookingStatusHistory.objects.create(
                    booking=booking, from_status=old, to_status=new_status, changed_by=request.user, note=note
                )
                log_admin_activity(request.user, f'Updated booking status to {new_status}', 'Booking', booking.enquiry_id, note, request)
                if booking.customer:
                    notify_user(booking.customer, f'Booking {booking.enquiry_id}: {booking.get_status_display()}', note or f'Status updated to {booking.get_status_display()}.', 'booking', f'/customer/bookings/{booking.enquiry_id}/')
                messages.success(request, f'Booking status updated to {booking.get_status_display()}.')
        elif action == 'assign_technician':
            tech = get_object_or_404(User, pk=request.POST.get('technician_id'), role=User.ROLE_TECHNICIAN)
            if not tech.technician_profile.is_verified:
                messages.error(request, 'Cannot assign unverified or suspended technician.')
            else:
                old = booking.status
                booking.assigned_technician = tech
                booking.status = Booking.STATUS_TECHNICIAN_ASSIGNED
                booking.save()
                JobAssignment.objects.create(booking=booking, technician=tech, assigned_by=request.user)
                BookingStatusHistory.objects.create(
                    booking=booking, from_status=old, to_status=Booking.STATUS_TECHNICIAN_ASSIGNED,
                    changed_by=request.user, note=f'Assigned technician {tech.full_name}',
                )
                notify_user(tech, f'New Job Assigned: {booking.enquiry_id}', f'{booking.service_name_snapshot} on {booking.preferred_date}', 'job', f'/technician/jobs/{booking.enquiry_id}/')
                if booking.customer:
                    notify_user(booking.customer, f'Technician Assigned ({booking.enquiry_id})', f'{tech.full_name} has been assigned to your booking.', 'booking', f'/customer/bookings/{booking.enquiry_id}/')
                log_admin_activity(request.user, 'Assigned technician', 'Booking', booking.enquiry_id, tech.full_name, request)
                messages.success(request, f'Assigned {tech.full_name} to {booking.enquiry_id}.')
        elif action == 'update_pricing':
            booking.estimated_price = Decimal(request.POST.get('estimated_price') or 0)
            booking.additional_charges = Decimal(request.POST.get('additional_charges') or 0)
            booking.material_charges = Decimal(request.POST.get('material_charges') or 0)
            booking.emergency_charges = Decimal(request.POST.get('emergency_charges') or 0)
            booking.discount_amount = Decimal(request.POST.get('discount_amount') or 0)
            booking.tax_amount = Decimal(request.POST.get('tax_amount') or 0)
            booking.admin_notes = request.POST.get('admin_notes', booking.admin_notes)
            booking.recalculate_final_price(save=False)
            booking.save()
            log_admin_activity(request.user, 'Updated booking pricing', 'Booking', booking.enquiry_id, f'Final: {booking.final_price}', request)
            messages.success(request, f'Pricing updated. Final Price: {biz.currency_symbol}{booking.final_price}')
        return redirect('dashboard:booking_detail_admin', enquiry_id=enquiry_id)

    confirm_msg = biz.booking_confirmation_template.format(
        customer_name=booking.customer_name,
        enquiry_id=booking.enquiry_id,
        service_name=booking.service_name_snapshot,
        preferred_date=booking.preferred_date.strftime('%Y-%m-%d'),
        preferred_time=booking.preferred_time,
    )
    customer_wa_confirm = build_whatsapp_url(booking.customer_whatsapp or booking.customer_phone, confirm_msg)
    return render(request, 'admin_panel/booking_detail.html', {
        'booking': booking,
        'verified_techs': verified_techs,
        'status_choices': Booking.STATUS_CHOICES,
        'customer_wa_confirm': customer_wa_confirm,
    })


@admin_permission_required('can_manage_bookings')
def kanban_board(request):
    columns = [
        ('New Enquiries', Booking.STATUS_ENQUIRY_SUBMITTED, 'secondary'),
        ('Pending Confirmation', Booking.STATUS_WHATSAPP_INITIATED, 'info'),
        ('Confirmed', Booking.STATUS_CONFIRMED, 'primary'),
        ('Technician Assigned', Booking.STATUS_TECHNICIAN_ASSIGNED, 'indigo'),
        ('In Progress', Booking.STATUS_WORK_STARTED, 'warning'),
        ('Completed', Booking.STATUS_WORK_COMPLETED, 'success'),
        ('Payment Pending', Booking.STATUS_PAYMENT_PENDING, 'danger'),
        ('Closed', Booking.STATUS_CLOSED, 'dark'),
        ('Cancelled', Booking.STATUS_CANCELLED, 'danger'),
    ]
    board_data = []
    for title, status_key, color in columns:
        if status_key == Booking.STATUS_WORK_STARTED:
            items = Booking.objects.filter(status__in=[Booking.STATUS_ON_THE_WAY, Booking.STATUS_WORK_STARTED])
        elif status_key == Booking.STATUS_WORK_COMPLETED:
            items = Booking.objects.filter(status__in=[Booking.STATUS_WORK_COMPLETED, Booking.STATUS_PAYMENT_COMPLETED])
        else:
            items = Booking.objects.filter(status=status_key)
        board_data.append({
            'title': title,
            'status_key': status_key,
            'color': color,
            'items': items.select_related('assigned_technician', 'category')[:25],
        })
    return render(request, 'admin_panel/kanban.html', {'board_data': board_data, 'status_choices': Booking.STATUS_CHOICES})


@admin_permission_required('can_manage_bookings')
def kanban_move_status(request):
    if request.method == 'POST':
        enquiry_id = request.POST.get('enquiry_id')
        new_status = request.POST.get('new_status')
        booking = get_object_or_404(Booking, enquiry_id=enquiry_id)
        if new_status in dict(Booking.STATUS_CHOICES):
            old = booking.status
            booking.status = new_status
            booking.save(update_fields=['status', 'updated_at'])
            BookingStatusHistory.objects.create(
                booking=booking, from_status=old, to_status=new_status, changed_by=request.user, note='Moved via Kanban board'
            )
            log_admin_activity(request.user, f'Kanban move {old} -> {new_status}', 'Booking', booking.enquiry_id, '', request)
            return JsonResponse({'ok': True, 'status': booking.get_status_display()})
    return JsonResponse({'ok': False}, status=400)


@admin_permission_required('can_manage_bookings')
def assign_jobs_queue(request):
    unassigned = Booking.objects.filter(
        assigned_technician__isnull=True
    ).exclude(status=Booking.STATUS_CANCELLED).select_related('category', 'service')
    verified_techs = User.objects.filter(
        role=User.ROLE_TECHNICIAN, is_suspended=False, technician_profile__verification_status='approved'
    ).select_related('technician_profile')
    return render(request, 'admin_panel/assign_jobs.html', {
        'unassigned': unassigned,
        'verified_techs': verified_techs,
    })


# ==================== CUSTOMERS, TECHNICIANS & KYC ====================

@admin_permission_required('can_manage_customers')
def customers_manage(request):
    q = request.GET.get('q', '').strip()
    qs = User.objects.filter(role=User.ROLE_CUSTOMER).select_related('customer_profile').annotate(
        bookings_count=Count('bookings'),
        ltv=Sum('bookings__final_price', filter=Q(bookings__payment_status='paid')),
    )
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))

    if request.GET.get('export') == 'csv':
        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="letsto_customers.csv"'
        writer = csv.writer(resp)
        writer.writerow(['Full Name', 'Phone', 'WhatsApp', 'Email', 'Bookings', 'LTV', 'Status'])
        for c in qs:
            writer.writerow([c.full_name, c.phone, c.whatsapp_number, c.email, c.bookings_count, c.ltv or 0, 'Suspended' if c.is_suspended else 'Active'])
        return resp

    if request.method == 'POST':
        cust = get_object_or_404(User, pk=request.POST.get('user_id'), role=User.ROLE_CUSTOMER)
        action = request.POST.get('action')
        if action == 'toggle_suspend':
            cust.is_suspended = not cust.is_suspended
            cust.suspension_reason = request.POST.get('reason', '')
            cust.save(update_fields=['is_suspended', 'suspension_reason'])
            log_admin_activity(request.user, 'Toggled customer suspension', 'User', cust.pk, cust.full_name, request)
            messages.info(request, f'Customer {cust.full_name} status updated.')
        elif action == 'save_note':
            cp = cust.customer_profile
            cp.internal_notes = request.POST.get('internal_notes', '')
            cp.save(update_fields=['internal_notes'])
            messages.success(request, 'Internal note saved.')
        return redirect('dashboard:customers_manage')

    return render(request, 'admin_panel/customers_manage.html', {'customers': qs[:100], 'q': q})


@admin_permission_required('can_manage_technicians')
def technicians_manage(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'toggle_suspend':
            tech = get_object_or_404(User, pk=request.POST.get('user_id'), role=User.ROLE_TECHNICIAN)
            tech.is_suspended = not tech.is_suspended
            tech.save(update_fields=['is_suspended'])
            messages.info(request, f'Technician {tech.full_name} status updated.')
        elif action == 'update_commission':
            tech = get_object_or_404(User, pk=request.POST.get('user_id'), role=User.ROLE_TECHNICIAN)
            rate = request.POST.get('custom_commission_rate', '').strip()
            tp = tech.technician_profile
            tp.custom_commission_rate = Decimal(rate) if rate else None
            tp.save(update_fields=['custom_commission_rate'])
            messages.success(request, f'Commission rate updated for {tech.full_name}.')
        return redirect('dashboard:technicians_manage')

    techs = User.objects.filter(role=User.ROLE_TECHNICIAN).select_related('technician_profile').annotate(
        total_jobs=Count('assigned_bookings'),
        completed_jobs=Count('assigned_bookings', filter=Q(assigned_bookings__status__in=[Booking.STATUS_WORK_COMPLETED, Booking.STATUS_PAYMENT_COMPLETED, Booking.STATUS_CLOSED])),
        cancelled_jobs=Count('assigned_bookings', filter=Q(assigned_bookings__status=Booking.STATUS_CANCELLED)),
    )
    return render(request, 'admin_panel/technicians_manage.html', {'technicians': techs})


@admin_permission_required('can_verify_kyc')
def kyc_queue(request):
    if request.method == 'POST':
        user_obj = get_object_or_404(User, pk=request.POST.get('user_id'))
        decision = request.POST.get('decision')
        reason = request.POST.get('rejection_reason', '').strip()
        notes = request.POST.get('internal_notes', '').strip()

        ver, _ = Verification.objects.get_or_create(user=user_obj)
        if decision in ('approved', 'rejected', 'under_verification', 'suspended', 'pending_review'):
            ver.status = decision
            ver.reviewed_by = request.user
            ver.reviewed_at = timezone.now()
            ver.rejection_reason = reason
            ver.internal_notes = notes
            ver.save()

            if hasattr(user_obj, 'customer_profile'):
                user_obj.customer_profile.verification_status = decision
                user_obj.customer_profile.save(update_fields=['verification_status'])
            if hasattr(user_obj, 'technician_profile'):
                user_obj.technician_profile.verification_status = decision
                user_obj.technician_profile.save(update_fields=['verification_status'])
            if decision == 'suspended':
                user_obj.is_suspended = True
                user_obj.suspension_reason = reason
                user_obj.save(update_fields=['is_suspended', 'suspension_reason'])

            log_admin_activity(request.user, f'KYC {decision}', 'Verification', user_obj.pk, f'{user_obj.full_name}: {reason}', request)
            notify_user(user_obj, f'KYC Status: {ver.get_status_display()}', reason or f'Your verification status is now {ver.get_status_display()}.', 'kyc')
            messages.success(request, f'Verification updated to {ver.get_status_display()} for {user_obj.full_name}.')
        return redirect('dashboard:kyc_queue')

    verifications = Verification.objects.select_related('user', 'reviewed_by').order_by('-updated_at')
    docs_by_user = {}
    for doc in IdentityDocument.objects.filter(is_active=True):
        docs_by_user[doc.user_id] = doc
    for v in verifications:
        v.active_doc = docs_by_user.get(v.user_id)
    return render(request, 'admin_panel/kyc_queue.html', {'verifications': verifications})


# ==================== REVIEWS, COMPLAINTS, SETTINGS, ADMINS, LOGS ====================

@admin_permission_required()
def reviews_manage(request):
    if request.method == 'POST':
        rev = get_object_or_404(Review, pk=request.POST.get('review_id'))
        action = request.POST.get('action')
        if action == 'toggle_visibility':
            rev.is_visible = not rev.is_visible
            rev.save(update_fields=['is_visible'])
        elif action == 'respond':
            rev.admin_response = request.POST.get('admin_response', '')
            rev.save(update_fields=['admin_response'])
        messages.success(request, 'Review updated.')
        return redirect('dashboard:reviews_manage')
    reviews = Review.objects.select_related('booking', 'customer', 'service', 'technician')
    return render(request, 'admin_panel/reviews_manage.html', {'reviews': reviews})


@admin_permission_required()
def complaints_manage(request):
    if request.method == 'POST':
        comp = get_object_or_404(Complaint, pk=request.POST.get('complaint_id'))
        comp.status = request.POST.get('status', comp.status)
        comp.resolution_notes = request.POST.get('resolution_notes', comp.resolution_notes)
        comp.resolved_by = request.user
        comp.save()
        notify_user(comp.customer, f'Complaint Update: {comp.subject}', f'Status: {comp.get_status_display()}', 'complaint')
        messages.success(request, 'Complaint updated.')
        return redirect('dashboard:complaints_manage')
    complaints = Complaint.objects.select_related('booking', 'customer', 'resolved_by')
    return render(request, 'admin_panel/complaints_manage.html', {'complaints': complaints})


@admin_permission_required('can_manage_settings')
def website_manage(request):
    ws = WebsiteSettings.get_solo()
    if request.method == 'POST':
        for field in [
            'website_name', 'tagline', 'sub_tagline', 'description', 'contact_phone',
            'contact_email', 'business_address', 'primary_color', 'accent_color',
            'facebook_url', 'instagram_url', 'twitter_url', 'youtube_url', 'footer_text',
        ]:
            setattr(ws, field, request.POST.get(field, getattr(ws, field)))
        if request.FILES.get('logo'):
            ws.logo = request.FILES['logo']
        if request.FILES.get('favicon'):
            ws.favicon = request.FILES['favicon']
        ws.save()
        log_admin_activity(request.user, 'Updated Website Settings', 'WebsiteSettings', ws.pk, '', request)
        messages.success(request, 'Website settings saved.')
        return redirect('dashboard:website_manage')
    return render(request, 'admin_panel/website_manage.html', {'ws': ws})


@admin_permission_required('can_manage_settings')
def business_settings_view(request):
    biz = BusinessSettings.get_solo()
    if request.method == 'POST':
        for field in [
            'currency_code', 'currency_symbol', 'working_hours', 'weekly_holidays',
            'cancellation_policy', 'refund_policy', 'primary_whatsapp_number',
            'support_whatsapp_number', 'booking_whatsapp_number', 'default_booking_message',
            'booking_confirmation_template', 'technician_assignment_template',
            'job_completion_template', 'payment_reminder_template',
        ]:
            setattr(biz, field, request.POST.get(field, getattr(biz, field)))
        biz.tax_percentage = Decimal(request.POST.get('tax_percentage') or 0)
        biz.default_technician_commission = Decimal(request.POST.get('default_technician_commission') or 70)
        biz.default_platform_commission = Decimal('100.00') - biz.default_technician_commission
        biz.minimum_booking_amount = Decimal(request.POST.get('minimum_booking_amount') or 0)
        biz.cancellation_window_hours = int(request.POST.get('cancellation_window_hours') or 4)
        biz.emergency_service_enabled = request.POST.get('emergency_service_enabled') == 'on'
        biz.require_customer_verification_for_booking = request.POST.get('require_customer_verification_for_booking') == 'on'
        biz.allow_customer_registration = request.POST.get('allow_customer_registration') == 'on'
        biz.allow_technician_registration = request.POST.get('allow_technician_registration') == 'on'
        biz.save()
        log_admin_activity(request.user, 'Updated Business & WhatsApp Settings', 'BusinessSettings', biz.pk, '', request)
        messages.success(request, 'Business & WhatsApp settings updated.')
        return redirect('dashboard:business_settings')
    return render(request, 'admin_panel/business_settings.html', {'biz': biz})


@admin_permission_required('can_manage_admins')
def admin_users_manage(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create_role':
            RolePermission.objects.create(
                name=request.POST.get('name', '').strip(),
                description=request.POST.get('description', ''),
                can_manage_bookings=request.POST.get('can_manage_bookings') == 'on',
                can_manage_services=request.POST.get('can_manage_services') == 'on',
                can_manage_customers=request.POST.get('can_manage_customers') == 'on',
                can_manage_technicians=request.POST.get('can_manage_technicians') == 'on',
                can_verify_kyc=request.POST.get('can_verify_kyc') == 'on',
                can_manage_finance=request.POST.get('can_manage_finance') == 'on',
                can_approve_payouts=request.POST.get('can_approve_payouts') == 'on',
                can_manage_settings=request.POST.get('can_manage_settings') == 'on',
                can_manage_admins=request.POST.get('can_manage_admins') == 'on',
                can_view_reports=request.POST.get('can_view_reports') == 'on',
                can_view_audit_logs=request.POST.get('can_view_audit_logs') == 'on',
            )
            messages.success(request, 'Admin role permission created.')
        elif action == 'create_admin':
            phone = request.POST.get('phone', '').strip()
            if User.objects.filter(phone=phone).exists():
                messages.error(request, 'A user with this phone already exists.')
            else:
                u = User.objects.create_user(
                    username=phone,
                    email=request.POST.get('email', ''),
                    password=request.POST.get('password'),
                    role=User.ROLE_ADMIN,
                    full_name=request.POST.get('full_name', '').strip(),
                    phone=phone,
                    is_staff=True,
                )
                role_perm = RolePermission.objects.filter(pk=request.POST.get('role_permission_id')).first()
                AdminProfile.objects.create(
                    user=u,
                    department=request.POST.get('department', 'Operations'),
                    designation=request.POST.get('designation', 'Manager'),
                    role_permission=role_perm,
                )
                log_admin_activity(request.user, 'Created admin user', 'User', u.pk, u.full_name, request)
                messages.success(request, f'Admin user {u.full_name} created.')
        return redirect('dashboard:admin_users_manage')

    admins = User.objects.filter(role=User.ROLE_ADMIN).select_related('admin_profile__role_permission')
    roles = RolePermission.objects.all()
    return render(request, 'admin_panel/admin_users.html', {'admins': admins, 'roles': roles})


@admin_permission_required('can_view_audit_logs')
def activity_logs(request):
    logs = AdminActivityLog.objects.select_related('admin_user')[:100]
    doc_logs = DocumentAccessLog.objects.select_related('document__user', 'accessed_by')[:50]
    wa_logs = WhatsAppCommunicationLog.objects.select_related('booking', 'sender_user')[:50]
    return render(request, 'admin_panel/activity_logs.html', {
        'logs': logs,
        'doc_logs': doc_logs,
        'wa_logs': wa_logs,
    })
