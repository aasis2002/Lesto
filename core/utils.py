import re
import urllib.parse
import urllib.request
import json
from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from .models import AdminActivityLog, Notification, User


def get_client_ip(request):
    if not request:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_admin_activity(admin_user, action, target_model='', target_id='', details='', request=None):
    AdminActivityLog.objects.create(
        admin_user=admin_user if admin_user and admin_user.is_authenticated else None,
        action=action,
        target_model=target_model,
        target_id=str(target_id) if target_id else '',
        details=details,
        ip_address=get_client_ip(request),
    )


def notify_user(user, title, message, category='general', link=''):
    if not user:
        return None
    return Notification.objects.create(
        user=user,
        title=title,
        message=message,
        category=category,
        link=link,
    )


def notify_admins(title, message, category='admin', link=''):
    admins = User.objects.filter(role=User.ROLE_ADMIN, is_active=True)
    for admin in admins:
        Notification.objects.create(
            user=admin,
            title=title,
            message=message,
            category=category,
            link=link,
        )


def clean_phone_digits(phone):
    return re.sub(r'\D', '', str(phone or ''))


def build_whatsapp_url(phone_number, message_text):
    digits = clean_phone_digits(phone_number)
    encoded = urllib.parse.quote(message_text or '')
    return f"https://wa.me/{digits}?text={encoded}"


def send_whatsapp_api_message(recipient_phone, message_text):
    """
    Optional WhatsApp Business Cloud API sender.
    Only sends when WHATSAPP_API_TOKEN and WHATSAPP_PHONE_NUMBER_ID are configured.
    Never fakes automated synchronization.
    """
    token = getattr(settings, 'WHATSAPP_API_TOKEN', '')
    phone_id = getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')
    if not token or not phone_id:
        return False, 'WhatsApp Business API credentials not configured; using Click-to-Chat.'
    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    payload = json.dumps({
        'messaging_product': 'whatsapp',
        'to': clean_phone_digits(recipient_phone),
        'type': 'text',
        'text': {'body': message_text},
    }).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status in (200, 201), resp.read().decode('utf-8')
    except Exception as exc:
        return False, str(exc)


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('core:login')
            if request.user.is_suspended:
                messages.error(request, 'Your account is currently suspended. Please contact support.')
                return redirect('services:home')
            if request.user.is_superuser and User.ROLE_ADMIN in roles:
                return view_func(request, *args, **kwargs)
            if request.user.role not in roles:
                raise PermissionDenied('You do not have permission to access this area.')
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def admin_permission_required(perm_flag=None):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('core:login')
            if not request.user.is_admin_user:
                raise PermissionDenied('Administrator access required.')
            if request.user.is_suspended:
                raise PermissionDenied('Account suspended.')
            if perm_flag and not request.user.is_superuser:
                profile = getattr(request.user, 'admin_profile', None)
                if not profile or not profile.has_perm_flag(perm_flag):
                    raise PermissionDenied(f'Missing required permission: {perm_flag}')
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
