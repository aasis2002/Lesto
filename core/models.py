import uuid
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from .storage import PrivateMediaStorage

private_storage = PrivateMediaStorage()


class User(AbstractUser):
    ROLE_CUSTOMER = 'customer'
    ROLE_TECHNICIAN = 'technician'
    ROLE_ADMIN = 'admin'
    ROLE_CHOICES = [
        (ROLE_CUSTOMER, 'Customer'),
        (ROLE_TECHNICIAN, 'Technician'),
        (ROLE_ADMIN, 'Administrator'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_CUSTOMER, db_index=True)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=25, unique=True)
    whatsapp_number = models.CharField(max_length=25, blank=True)
    profile_photo = models.ImageField(upload_to='profiles/', blank=True, null=True)
    is_suspended = models.BooleanField(default=False)
    suspension_reason = models.TextField(blank=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.full_name or self.username} ({self.get_role_display()})"

    @property
    def display_whatsapp(self):
        return self.whatsapp_number or self.phone

    @property
    def is_customer(self):
        return self.role == self.ROLE_CUSTOMER

    @property
    def is_technician(self):
        return self.role == self.ROLE_TECHNICIAN

    @property
    def is_admin_user(self):
        return self.role == self.ROLE_ADMIN or self.is_superuser


class RolePermission(models.Model):
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    can_manage_bookings = models.BooleanField(default=True)
    can_manage_services = models.BooleanField(default=True)
    can_manage_customers = models.BooleanField(default=True)
    can_manage_technicians = models.BooleanField(default=True)
    can_verify_kyc = models.BooleanField(default=False)
    can_manage_finance = models.BooleanField(default=False)
    can_approve_payouts = models.BooleanField(default=False)
    can_manage_settings = models.BooleanField(default=False)
    can_manage_admins = models.BooleanField(default=False)
    can_view_reports = models.BooleanField(default=True)
    can_view_audit_logs = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class AdminProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='admin_profile')
    department = models.CharField(max_length=100, default='Operations')
    designation = models.CharField(max_length=100, default='Platform Administrator')
    role_permission = models.ForeignKey(
        RolePermission, on_delete=models.SET_NULL, null=True, blank=True, related_name='admins'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.full_name} - {self.designation}"

    def has_perm_flag(self, flag_name):
        if self.user.is_superuser:
            return True
        if not self.role_permission:
            return False
        return getattr(self.role_permission, flag_name, False)


class CustomerProfile(models.Model):
    VERIFICATION_CHOICES = [
        ('not_submitted', 'Not Submitted'),
        ('pending_review', 'Pending Review'),
        ('under_verification', 'Under Verification'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('suspended', 'Suspended'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='customer_profile')
    residential_address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    district = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    verification_status = models.CharField(max_length=30, choices=VERIFICATION_CHOICES, default='not_submitted', db_index=True)
    internal_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Customer: {self.user.full_name}"


class TechnicianProfile(models.Model):
    VERIFICATION_CHOICES = CustomerProfile.VERIFICATION_CHOICES

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='technician_profile')
    full_legal_name = models.CharField(max_length=150)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=30, blank=True)
    residential_address = models.TextField(blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    skills_summary = models.TextField(blank=True)
    previous_experience = models.TextField(blank=True)
    certificates_notes = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=120, blank=True)
    emergency_contact_phone = models.CharField(max_length=25, blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_name = models.CharField(max_length=120, blank=True)
    bank_account_number = models.CharField(max_length=60, blank=True)
    bank_branch = models.CharField(max_length=120, blank=True)
    payout_wallet_id = models.CharField(max_length=80, blank=True)
    verification_status = models.CharField(max_length=30, choices=VERIFICATION_CHOICES, default='not_submitted', db_index=True)
    custom_commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Optional custom technician commission % (overrides default)'
    )
    is_available = models.BooleanField(default=True)
    live_gps_consent = models.BooleanField(default=False)
    current_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    current_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    service_categories = models.ManyToManyField('services.ServiceCategory', blank=True, related_name='technicians')
    service_areas = models.ManyToManyField('services.ServiceArea', blank=True, related_name='technicians')
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    on_time_rate = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    internal_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Tech: {self.full_legal_name or self.user.full_name}"

    @property
    def is_verified(self):
        return self.verification_status == 'approved' and not self.user.is_suspended


class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    label = models.CharField(max_length=50, default='Home')
    full_address = models.TextField()
    landmark = models.CharField(max_length=150, blank=True)
    city = models.CharField(max_length=80)
    district = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f"{self.label}: {self.full_address[:40]}"


class IdentityDocument(models.Model):
    DOC_TYPE_CHOICES = [
        ('citizenship', 'Citizenship / National ID'),
        ('passport', 'Passport'),
        ('driving_license', 'Driving License'),
        ('voter_id', 'Voter ID'),
        ('other', 'Other Government ID'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='identity_documents')
    document_type = models.CharField(max_length=30, choices=DOC_TYPE_CHOICES, default='citizenship')
    document_number = models.CharField(max_length=80)
    front_image = models.FileField(
        upload_to='kyc_docs/', storage=private_storage,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])]
    )
    back_image = models.FileField(
        upload_to='kyc_docs/', storage=private_storage, blank=True, null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])]
    )
    address_proof = models.FileField(
        upload_to='kyc_docs/', storage=private_storage, blank=True, null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])]
    )
    certificate_file = models.FileField(
        upload_to='kyc_certs/', storage=private_storage, blank=True, null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])]
    )
    is_active = models.BooleanField(default=True)
    retention_until = models.DateField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.user.full_name} - {self.get_document_type_display()}"


class DocumentAccessLog(models.Model):
    document = models.ForeignKey(IdentityDocument, on_delete=models.CASCADE, related_name='access_logs')
    accessed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    purpose = models.CharField(max_length=150, default='KYC Review')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    accessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-accessed_at']


class Verification(models.Model):
    STATUS_CHOICES = CustomerProfile.VERIFICATION_CHOICES
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='verification_record')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='not_submitted', db_index=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_verifications')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.full_name} ({self.get_status_display()})"


class WebsiteSettings(models.Model):
    website_name = models.CharField(max_length=100, default='LetsTo')
    tagline = models.CharField(max_length=150, default='Book • Connect • Get It Done')
    sub_tagline = models.CharField(max_length=150, default='Your Trusted Home Service Partner')
    logo = models.ImageField(upload_to='branding/', blank=True, null=True)
    favicon = models.ImageField(upload_to='branding/', blank=True, null=True)
    description = models.TextField(
        default='LetsTo connects households and businesses with verified, skilled technicians for cleaning, electrical, plumbing, and home repair services.'
    )
    contact_phone = models.CharField(max_length=30, default='+977-9800000000')
    contact_email = models.EmailField(default='support@letsto.com')
    business_address = models.CharField(max_length=255, default='Kathmandu, Nepal')
    primary_color = models.CharField(max_length=20, default='#0B2C52')
    accent_color = models.CharField(max_length=20, default='#F97316')
    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    footer_text = models.CharField(max_length=255, default='© 2026 LetsTo Home Services. All rights reserved.')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.website_name

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class BusinessSettings(models.Model):
    currency_code = models.CharField(max_length=10, default='NPR')
    currency_symbol = models.CharField(max_length=10, default='NPR ')
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    default_technician_commission = models.DecimalField(max_digits=5, decimal_places=2, default=70)
    default_platform_commission = models.DecimalField(max_digits=5, decimal_places=2, default=30)
    minimum_booking_amount = models.DecimalField(max_digits=10, decimal_places=2, default=500)
    working_hours = models.CharField(max_length=100, default='07:00 AM - 08:00 PM')
    weekly_holidays = models.CharField(max_length=100, default='None (Open 7 Days)')
    emergency_service_enabled = models.BooleanField(default=True)
    require_customer_verification_for_booking = models.BooleanField(default=False)
    allow_customer_registration = models.BooleanField(default=True)
    allow_technician_registration = models.BooleanField(default=True)
    cancellation_window_hours = models.PositiveIntegerField(default=4)
    cancellation_policy = models.TextField(
        default='Customers may cancel a booking free of charge at least 4 hours before the scheduled visit.'
    )
    refund_policy = models.TextField(
        default='Approved refunds for prepaid bookings are processed within 3-5 business days.'
    )
    primary_whatsapp_number = models.CharField(max_length=25, default='9779800000000')
    support_whatsapp_number = models.CharField(max_length=25, default='9779800000000')
    booking_whatsapp_number = models.CharField(max_length=25, default='9779800000000')
    default_booking_message = models.TextField(
        default=(
            "Hello, I want to book your service.\n\n"
            "Enquiry ID: {enquiry_id}\n"
            "Customer Name: {customer_name}\n"
            "Service: {service_name}\n"
            "Category: {category_name}\n"
            "Address: {address}\n"
            "Preferred Date: {preferred_date}\n"
            "Preferred Time: {preferred_time}\n"
            "Description: {description}\n\n"
            "Please contact me regarding availability and pricing."
        )
    )
    booking_confirmation_template = models.TextField(
        default='Hello {customer_name}, your LetsTo booking {enquiry_id} for {service_name} on {preferred_date} at {preferred_time} is CONFIRMED.'
    )
    technician_assignment_template = models.TextField(
        default='Hello {customer_name}, technician {technician_name} ({technician_phone}) has been assigned to your booking {enquiry_id}.'
    )
    job_completion_template = models.TextField(
        default='Hello {customer_name}, your service {service_name} ({enquiry_id}) is completed. Final amount: {amount}. Thank you for choosing LetsTo!'
    )
    payment_reminder_template = models.TextField(
        default='Hello {customer_name}, gentle reminder for pending payment of {amount} for booking {enquiry_id}.'
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Business Settings ({self.currency_code})"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=150)
    message = models.TextField()
    category = models.CharField(max_length=50, default='general')
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.full_name}: {self.title}"


class WhatsAppCommunicationLog(models.Model):
    DIRECTION_CHOICES = [
        ('outbound', 'Outbound'),
        ('inbound', 'Inbound'),
        ('click_to_chat', 'Click-to-Chat Initiated'),
    ]
    booking = models.ForeignKey('bookings.Booking', on_delete=models.CASCADE, null=True, blank=True, related_name='whatsapp_logs')
    sender_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    recipient_phone = models.CharField(max_length=30)
    direction = models.CharField(max_length=20, choices=DIRECTION_CHOICES, default='click_to_chat')
    message_body = models.TextField()
    template_name = models.CharField(max_length=80, blank=True)
    wa_link = models.TextField(blank=True)
    status = models.CharField(max_length=40, default='initiated')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class AdminActivityLog(models.Model):
    admin_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='activity_logs')
    action = models.CharField(max_length=120)
    target_model = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.action} by {self.admin_user} at {self.created_at:%Y-%m-%d %H:%M}"
