import mimetypes
import os
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .forms import CustomerRegistrationForm, KYCDocumentForm, LoginForm, TechnicianRegistrationForm
from .models import (
    BusinessSettings, CustomerProfile, DocumentAccessLog, IdentityDocument,
    Notification, TechnicianProfile, User, Verification, Address,
)
from .utils import get_client_ip, notify_admins, notify_user


def login_view(request):
    if request.user.is_authenticated:
        return redirect('core:role_redirect')
    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        identifier = form.cleaned_data['identifier'].strip()
        password = form.cleaned_data['password']
        user_obj = User.objects.filter(
            Q(username__iexact=identifier) | Q(phone=identifier) | Q(email__iexact=identifier)
        ).first()

        if user_obj and user_obj.locked_until and user_obj.locked_until > timezone.now():
            messages.error(request, 'Too many failed login attempts. Please try again in 15 minutes.')
            return render(request, 'auth/login.html', {'form': form})

        auth_user = None
        if user_obj:
            auth_user = authenticate(request, username=user_obj.username, password=password)

        if auth_user is not None:
            if auth_user.is_suspended:
                messages.error(request, f'Account suspended: {auth_user.suspension_reason or "Contact support."}')
                return render(request, 'auth/login.html', {'form': form})
            user_obj.failed_login_attempts = 0
            user_obj.locked_until = None
            user_obj.save(update_fields=['failed_login_attempts', 'locked_until'])
            login(request, auth_user)
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('core:role_redirect')
        else:
            if user_obj:
                user_obj.failed_login_attempts += 1
                if user_obj.failed_login_attempts >= 5:
                    user_obj.locked_until = timezone.now() + timedelta(minutes=15)
                user_obj.save(update_fields=['failed_login_attempts', 'locked_until'])
            messages.error(request, 'Invalid credentials. Please check your phone/username and password.')

    return render(request, 'auth/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been signed out.')
    return redirect('services:home')


@login_required
def role_redirect(request):
    if request.user.is_admin_user:
        return redirect('dashboard:overview')
    if request.user.is_technician:
        return redirect('bookings:technician_dashboard')
    return redirect('bookings:customer_dashboard')


def register_customer(request):
    biz = BusinessSettings.get_solo()
    if not biz.allow_customer_registration:
        messages.error(request, 'Customer self-registration is currently disabled by administrator.')
        return redirect('services:home')

    form = CustomerRegistrationForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        with transaction.atomic():
            username = cd['phone']
            user = User.objects.create_user(
                username=username,
                email=cd.get('email') or '',
                password=cd['password'],
                role=User.ROLE_CUSTOMER,
                full_name=cd['full_name'],
                phone=cd['phone'],
                whatsapp_number=cd.get('whatsapp_number') or cd['phone'],
                profile_photo=cd.get('profile_photo'),
            )
            has_doc = bool(cd.get('front_image') and cd.get('document_number'))
            v_status = 'pending_review' if has_doc else 'not_submitted'
            CustomerProfile.objects.create(
                user=user,
                residential_address=cd['residential_address'],
                city=cd['city'],
                district=cd['district'],
                state=cd.get('state', ''),
                postal_code=cd.get('postal_code', ''),
                verification_status=v_status,
            )
            Address.objects.create(
                user=user,
                label='Home',
                full_address=cd['residential_address'],
                city=cd['city'],
                district=cd['district'],
                state=cd.get('state', ''),
                postal_code=cd.get('postal_code', ''),
                is_default=True,
            )
            Verification.objects.create(
                user=user,
                status=v_status,
                submitted_at=timezone.now() if has_doc else None,
            )
            if has_doc:
                IdentityDocument.objects.create(
                    user=user,
                    document_type=cd.get('document_type') or 'citizenship',
                    document_number=cd['document_number'],
                    front_image=cd['front_image'],
                )
                notify_admins(
                    'New Customer KYC Submitted',
                    f'{user.full_name} registered and submitted KYC documents.',
                    category='kyc',
                    link='/admin-panel/kyc/'
                )
            else:
                notify_admins(
                    'New Customer Registered',
                    f'{user.full_name} ({user.phone}) created a customer account.',
                    category='customer',
                    link='/admin-panel/customers/'
                )
            notify_user(user, 'Welcome to LetsTo!', 'Your customer account has been created successfully.', 'welcome')
        login(request, user)
        messages.success(request, 'Welcome to LetsTo! Your account is ready.')
        return redirect('bookings:customer_dashboard')

    return render(request, 'auth/register_customer.html', {'form': form})


def register_technician(request):
    biz = BusinessSettings.get_solo()
    if not biz.allow_technician_registration:
        messages.error(request, 'Technician registration is currently closed.')
        return redirect('services:home')

    form = TechnicianRegistrationForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        with transaction.atomic():
            user = User.objects.create_user(
                username=cd['phone'],
                email=cd['email'],
                password=cd['password'],
                role=User.ROLE_TECHNICIAN,
                full_name=cd['full_legal_name'],
                phone=cd['phone'],
                whatsapp_number=cd.get('whatsapp_number') or cd['phone'],
                profile_photo=cd.get('profile_photo'),
            )
            tech = TechnicianProfile.objects.create(
                user=user,
                full_legal_name=cd['full_legal_name'],
                date_of_birth=cd.get('date_of_birth'),
                gender=cd.get('gender', ''),
                residential_address=cd['residential_address'],
                experience_years=cd['experience_years'],
                skills_summary=cd['skills_summary'],
                previous_experience=cd.get('previous_experience', ''),
                certificates_notes=cd.get('certificates_notes', ''),
                emergency_contact_name=cd['emergency_contact_name'],
                emergency_contact_phone=cd['emergency_contact_phone'],
                bank_name=cd.get('bank_name', ''),
                bank_account_name=cd.get('bank_account_name', ''),
                bank_account_number=cd.get('bank_account_number', ''),
                payout_wallet_id=cd.get('payout_wallet_id', ''),
                verification_status='pending_review',
            )
            tech.service_categories.set(cd['service_categories'])
            if cd.get('service_areas'):
                tech.service_areas.set(cd['service_areas'])

            IdentityDocument.objects.create(
                user=user,
                document_type=cd['document_type'],
                document_number=cd['document_number'],
                front_image=cd['front_image'],
                back_image=cd.get('back_image'),
                certificate_file=cd.get('certificate_file'),
            )
            Verification.objects.create(
                user=user,
                status='pending_review',
                submitted_at=timezone.now(),
            )
            notify_admins(
                'New Technician Application',
                f'{user.full_name} applied as a technician and submitted KYC for approval.',
                category='kyc',
                link='/admin-panel/kyc/'
            )
            notify_user(
                user,
                'Application Submitted',
                'Your technician profile and KYC documents are pending administrator approval.',
                'kyc'
            )
        login(request, user)
        messages.success(request, 'Application submitted! Our team will verify your documents before assigning jobs.')
        return redirect('bookings:technician_dashboard')

    return render(request, 'auth/register_technician.html', {'form': form})


@login_required
def upload_kyc(request):
    form = KYCDocumentForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            IdentityDocument.objects.filter(user=request.user, is_active=True).update(is_active=False)
            doc = form.save(commit=False)
            doc.user = request.user
            doc.is_active = True
            doc.save()

            ver, _ = Verification.objects.get_or_create(user=request.user)
            ver.status = 'pending_review'
            ver.submitted_at = timezone.now()
            ver.rejection_reason = ''
            ver.save()

            if hasattr(request.user, 'customer_profile'):
                request.user.customer_profile.verification_status = 'pending_review'
                request.user.customer_profile.save(update_fields=['verification_status'])
            if hasattr(request.user, 'technician_profile'):
                request.user.technician_profile.verification_status = 'pending_review'
                request.user.technician_profile.save(update_fields=['verification_status'])

            notify_admins(
                'KYC Document Uploaded',
                f'{request.user.full_name} uploaded new KYC documents for review.',
                category='kyc',
                link='/admin-panel/kyc/'
            )
        messages.success(request, 'KYC documents submitted for verification.')
        return redirect('core:role_redirect')
    return render(request, 'auth/upload_kyc.html', {'form': form})


@login_required
def serve_kyc_document(request, doc_id, field_name):
    """
    Securely serves private KYC documents.
    Only accessible to the document owner or an administrator with can_verify_kyc permission.
    Logs every access in DocumentAccessLog.
    """
    doc = get_object_or_404(IdentityDocument, pk=doc_id)
    is_owner = doc.user_id == request.user.id
    is_authorized_admin = False
    if request.user.is_admin_user:
        if request.user.is_superuser:
            is_authorized_admin = True
        else:
            ap = getattr(request.user, 'admin_profile', None)
            is_authorized_admin = bool(ap and ap.has_perm_flag('can_verify_kyc'))

    if not (is_owner or is_authorized_admin):
        raise PermissionDenied('Unauthorized access to identity document.')

    if field_name not in ('front_image', 'back_image', 'address_proof', 'certificate_file'):
        raise Http404('Invalid document field.')

    file_field = getattr(doc, field_name, None)
    if not file_field:
        raise Http404('Document file not found.')

    DocumentAccessLog.objects.create(
        document=doc,
        accessed_by=request.user,
        purpose=f'Viewed {field_name}',
        ip_address=get_client_ip(request),
    )
    content_type, _ = mimetypes.guess_type(file_field.name)
    return FileResponse(file_field.open('rb'), content_type=content_type or 'application/octet-stream')


@login_required
def notifications_list(request):
    items = Notification.objects.filter(user=request.user)
    if request.method == 'POST':
        items.filter(is_read=False).update(is_read=True)
        messages.success(request, 'All notifications marked as read.')
        return redirect('core:notifications')
    return render(request, 'auth/notifications.html', {'notifications': items})
