import uuid
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone


def generate_enquiry_id():
    stamp = timezone.now().strftime('%y%m%d')
    short = uuid.uuid4().hex[:5].upper()
    return f"LT-{stamp}-{short}"


class Booking(models.Model):
    STATUS_ENQUIRY_SUBMITTED = 'enquiry_submitted'
    STATUS_WHATSAPP_INITIATED = 'whatsapp_initiated'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_TECHNICIAN_ASSIGNED = 'technician_assigned'
    STATUS_ON_THE_WAY = 'on_the_way'
    STATUS_WORK_STARTED = 'work_started'
    STATUS_WORK_COMPLETED = 'work_completed'
    STATUS_PAYMENT_PENDING = 'payment_pending'
    STATUS_PAYMENT_COMPLETED = 'payment_completed'
    STATUS_CLOSED = 'closed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_ENQUIRY_SUBMITTED, 'Enquiry Submitted'),
        (STATUS_WHATSAPP_INITIATED, 'WhatsApp Contact Initiated'),
        (STATUS_CONFIRMED, 'Booking Confirmed'),
        (STATUS_TECHNICIAN_ASSIGNED, 'Technician Assigned'),
        (STATUS_ON_THE_WAY, 'Technician On The Way'),
        (STATUS_WORK_STARTED, 'Work Started'),
        (STATUS_WORK_COMPLETED, 'Work Completed'),
        (STATUS_PAYMENT_PENDING, 'Payment Pending'),
        (STATUS_PAYMENT_COMPLETED, 'Payment Completed'),
        (STATUS_CLOSED, 'Booking Closed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded'),
        ('failed', 'Failed'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('digital_wallet', 'Digital Wallet'),
        ('esewa', 'eSewa'),
        ('khalti', 'Khalti'),
        ('manual', 'Manual Verification'),
    ]

    enquiry_id = models.CharField(max_length=30, unique=True, default=generate_enquiry_id, db_index=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')
    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=25)
    customer_whatsapp = models.CharField(max_length=25, blank=True)

    category = models.ForeignKey('services.ServiceCategory', on_delete=models.SET_NULL, null=True, related_name='bookings')
    subcategory = models.ForeignKey('services.ServiceSubcategory', on_delete=models.SET_NULL, null=True, blank=True)
    service = models.ForeignKey('services.Service', on_delete=models.SET_NULL, null=True, related_name='bookings')
    service_name_snapshot = models.CharField(max_length=150)

    description = models.TextField()
    preferred_date = models.DateField()
    preferred_time = models.CharField(max_length=40)
    address = models.TextField()
    city = models.CharField(max_length=80, blank=True)
    service_area = models.ForeignKey('services.ServiceArea', on_delete=models.SET_NULL, null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    assigned_technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_bookings'
    )

    estimated_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    additional_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    material_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    emergency_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    final_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_ENQUIRY_SUBMITTED, db_index=True)
    payment_status = models.CharField(max_length=25, choices=PAYMENT_STATUS_CHOICES, default='unpaid', db_index=True)
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHOD_CHOICES, default='cash')

    admin_notes = models.TextField(blank=True)
    cancellation_reason = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='cancelled_bookings'
    )
    whatsapp_redirect_url = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def recalculate_final_price(self, save=True):
        subtotal = (
            Decimal(self.estimated_price or 0)
            + Decimal(self.additional_charges or 0)
            + Decimal(self.material_charges or 0)
            + Decimal(self.emergency_charges or 0)
            - Decimal(self.discount_amount or 0)
        )
        if subtotal < 0:
            subtotal = Decimal('0.00')
        self.final_price = subtotal + Decimal(self.tax_amount or 0)
        if save:
            self.save(update_fields=['final_price', 'updated_at'])
        return self.final_price

    @property
    def status_badge_color(self):
        mapping = {
            'enquiry_submitted': 'secondary',
            'whatsapp_initiated': 'info',
            'confirmed': 'primary',
            'technician_assigned': 'indigo',
            'on_the_way': 'warning',
            'work_started': 'warning',
            'work_completed': 'success',
            'payment_pending': 'danger',
            'payment_completed': 'success',
            'closed': 'dark',
            'cancelled': 'danger',
        }
        return mapping.get(self.status, 'secondary')

    def __str__(self):
        return f"{self.enquiry_id} - {self.service_name_snapshot}"


class BookingStatusHistory(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='status_history')
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class JobAssignment(models.Model):
    ACCEPTANCE_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('reassigned', 'Reassigned'),
    ]
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='assignments')
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='job_assignments')
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='dispatched_jobs')
    acceptance_status = models.CharField(max_length=20, choices=ACCEPTANCE_CHOICES, default='pending')
    rejection_reason = models.TextField(blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-assigned_at']


class JobUpdate(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='job_updates')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    note = models.TextField()
    is_completion_report = models.BooleanField(default=False)
    requested_material_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class JobAttachment(models.Model):
    STAGE_CHOICES = [
        ('customer_enquiry', 'Customer Enquiry Photo'),
        ('before_work', 'Before Work'),
        ('after_work', 'After Work'),
        ('feedback', 'Customer Feedback'),
    ]
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='attachments')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    stage = models.CharField(max_length=25, choices=STAGE_CHOICES, default='customer_enquiry')
    file = models.ImageField(upload_to='job_photos/')
    caption = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Review(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='review')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews_given')
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews_received')
    service = models.ForeignKey('services.Service', on_delete=models.SET_NULL, null=True, related_name='reviews')
    service_rating = models.PositiveSmallIntegerField(default=5)
    technician_rating = models.PositiveSmallIntegerField(default=5)
    comment = models.TextField()
    photo = models.ImageField(upload_to='reviews/', blank=True, null=True)
    is_visible = models.BooleanField(default=True)
    admin_response = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Complaint(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('investigating', 'Investigating'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name='complaints')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='complaints')
    subject = models.CharField(max_length=150)
    description = models.TextField()
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='open')
    resolution_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_complaints')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
