from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from core.models import TechnicianProfile
from bookings.models import Review
from bookings.forms import WhatsAppBookingForm
from .models import Service, ServiceArea, ServiceCategory, ServiceSubcategory


def home(request):
    categories = ServiceCategory.objects.filter(is_active=True, is_deleted=False).annotate(
        service_count=Count('services', filter=Q(services__is_available=True, services__is_deleted=False))
    )
    featured_services = Service.objects.filter(
        is_available=True, is_deleted=False, is_featured=True
    ).select_related('category', 'subcategory')[:8]
    popular_services = Service.objects.filter(
        is_available=True, is_deleted=False, is_popular=True
    ).select_related('category', 'subcategory')[:8]
    if not popular_services.exists():
        popular_services = Service.objects.filter(is_available=True, is_deleted=False)[:8]

    verified_technicians = TechnicianProfile.objects.filter(
        verification_status='approved', user__is_suspended=False
    ).select_related('user').prefetch_related('service_categories')[:6]
    testimonials = Review.objects.filter(is_visible=True).select_related('customer', 'service')[:6]
    areas = ServiceArea.objects.filter(is_active=True)

    return render(request, 'public/home.html', {
        'categories': categories,
        'featured_services': featured_services,
        'popular_services': popular_services,
        'verified_technicians': verified_technicians,
        'testimonials': testimonials,
        'areas': areas,
    })


def service_list(request):
    qs = Service.objects.filter(is_available=True, is_deleted=False).select_related('category', 'subcategory')
    q = request.GET.get('q', '').strip()
    cat_slug = request.GET.get('category', '').strip()
    sub_slug = request.GET.get('subcategory', '').strip()
    area_id = request.GET.get('area', '').strip()
    min_price = request.GET.get('min_price', '').strip()
    max_price = request.GET.get('max_price', '').strip()
    sort = request.GET.get('sort', 'featured')

    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(short_description__icontains=q)
            | Q(description__icontains=q)
            | Q(category__name__icontains=q)
        )
    if cat_slug:
        qs = qs.filter(category__slug=cat_slug)
    if sub_slug:
        qs = qs.filter(subcategory__slug=sub_slug)
    if area_id.isdigit():
        qs = qs.filter(service_areas__id=int(area_id))
    if min_price:
        try:
            qs = qs.filter(base_price__gte=float(min_price))
        except ValueError:
            pass
    if max_price:
        try:
            qs = qs.filter(base_price__lte=float(max_price))
        except ValueError:
            pass

    if sort == 'price_low':
        qs = qs.order_by('base_price')
    elif sort == 'price_high':
        qs = qs.order_by('-base_price')
    elif sort == 'newest':
        qs = qs.order_by('-created_at')
    else:
        qs = qs.order_by('-is_featured', '-is_popular', 'name')

    categories = ServiceCategory.objects.filter(is_active=True, is_deleted=False).prefetch_related('subcategories')
    areas = ServiceArea.objects.filter(is_active=True)

    return render(request, 'public/service_list.html', {
        'services': qs.distinct(),
        'categories': categories,
        'areas': areas,
        'filters': {
            'q': q,
            'category': cat_slug,
            'subcategory': sub_slug,
            'area': area_id,
            'min_price': min_price,
            'max_price': max_price,
            'sort': sort,
        },
    })


def service_detail(request, slug):
    service = get_object_or_404(
        Service.objects.select_related('category', 'subcategory').prefetch_related('service_areas', 'gallery_images'),
        slug=slug,
        is_deleted=False,
    )
    reviews = Review.objects.filter(service=service, is_visible=True).select_related('customer')
    related_services = Service.objects.filter(
        category=service.category, is_available=True, is_deleted=False
    ).exclude(pk=service.pk)[:4]

    initial = {}
    if request.user.is_authenticated:
        initial['customer_name'] = request.user.full_name
        initial['customer_phone'] = request.user.phone
        initial['customer_whatsapp'] = request.user.display_whatsapp
        default_addr = request.user.addresses.filter(is_default=True).first()
        if default_addr:
            initial['address'] = default_addr.full_address
            initial['city'] = default_addr.city

    booking_form = WhatsAppBookingForm(initial=initial, service=service)
    included_items = [line.strip() for line in (service.whats_included or '').splitlines() if line.strip()]

    return render(request, 'public/service_detail.html', {
        'service': service,
        'reviews': reviews,
        'related_services': related_services,
        'booking_form': booking_form,
        'included_items': included_items,
    })


def ajax_subcategories(request):
    cat_id = request.GET.get('category_id')
    subs = ServiceSubcategory.objects.filter(category_id=cat_id, is_active=True).values('id', 'name')
    return JsonResponse({'subcategories': list(subs)})
