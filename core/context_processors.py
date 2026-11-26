from .models import WebsiteSettings, BusinessSettings, Notification
from services.models import ServiceArea, ServiceCategory


def site_settings(request):
    website = WebsiteSettings.get_solo()
    business = BusinessSettings.get_solo()
    unread_count = 0
    recent_notifications = []
    if request.user.is_authenticated:
        qs = Notification.objects.filter(user=request.user)
        unread_count = qs.filter(is_read=False).count()
        recent_notifications = list(qs[:6])
    return {
        'website_settings': website,
        'business_settings': business,
        'unread_notifications_count': unread_count,
        'recent_notifications': recent_notifications,
        'global_service_areas': ServiceArea.objects.filter(is_active=True),
        'global_categories': ServiceCategory.objects.filter(is_active=True, is_deleted=False)[:8],
    }
