from django.db import models
from django.utils.text import slugify


class ServiceArea(models.Model):
    name = models.CharField(max_length=100)
    city = models.CharField(max_length=80)
    district = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['city', 'name']
        unique_together = ('name', 'city')

    def __str__(self):
        return f"{self.name}, {self.city}"


class ServiceCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    icon_name = models.CharField(max_length=50, default='wrench', help_text='Lucide icon name')
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = 'Service Categories'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ServiceSubcategory(models.Model):
    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE, related_name='subcategories')
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = ('category', 'name')

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.category.name}-{self.name}")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.category.name} → {self.name}"


class Service(models.Model):
    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE, related_name='services')
    subcategory = models.ForeignKey(ServiceSubcategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='services')
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    short_description = models.CharField(max_length=255)
    description = models.TextField()
    whats_included = models.TextField(blank=True, help_text='One item per line')
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    promo_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_duration = models.CharField(max_length=60, default='1 - 2 Hours')
    technician_commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Leave blank to use platform default commission %'
    )
    image = models.ImageField(upload_to='services/', blank=True, null=True)
    service_areas = models.ManyToManyField(ServiceArea, blank=True, related_name='services')
    is_featured = models.BooleanField(default=False, db_index=True)
    is_popular = models.BooleanField(default=False)
    is_available = models.BooleanField(default=True, db_index=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_featured', 'name']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug = base
            idx = 1
            while Service.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{idx}"
                idx += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def effective_price(self):
        if self.promo_price and self.promo_price < self.base_price:
            return self.promo_price
        return self.base_price

    @property
    def average_rating(self):
        reviews = self.reviews.filter(is_visible=True)
        if not reviews.exists():
            return 0
        return round(sum(r.service_rating for r in reviews) / reviews.count(), 1)

    def __str__(self):
        return self.name


class ServiceImage(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='gallery_images')
    image = models.ImageField(upload_to='services/gallery/')
    caption = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
