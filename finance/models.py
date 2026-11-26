import uuid
from decimal import Decimal
from django.conf import settings
from django.db import models


class Payment(models.Model):
    METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('digital_wallet', 'Digital Wallet'),
        ('esewa', 'eSewa'),
        ('khalti', 'Khalti'),
        ('manual', 'Manual Verification'),
    ]
    STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded'),
        ('failed', 'Failed'),
    ]
    reference_id = models.CharField(max_length=40, unique=True, default=uuid.uuid4)
    booking = models.ForeignKey('bookings.Booking', on_delete=models.CASCADE, related_name='payments')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=30, choices=METHOD_CHOICES, default='cash')
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='paid')
    transaction_code = models.CharField(max_length=100, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_payments')
    notes = models.TextField(blank=True)
    paid_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-paid_at']

    def save(self, *args, **kwargs):
        if not self.reference_id:
            self.reference_id = f"PAY-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)


class Refund(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('processed', 'Processed'),
        ('rejected', 'Rejected'),
    ]
    booking = models.ForeignKey('bookings.Booking', on_delete=models.CASCADE, related_name='refunds')
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='refunds')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='processed')
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class TechnicianCommission(models.Model):
    booking = models.OneToOneField('bookings.Booking', on_delete=models.CASCADE, related_name='commission_record')
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='commissions')
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    technician_rate = models.DecimalField(max_digits=5, decimal_places=2)
    platform_rate = models.DecimalField(max_digits=5, decimal_places=2)
    technician_amount = models.DecimalField(max_digits=12, decimal_places=2)
    platform_amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_paid_out = models.BooleanField(default=False)
    payout = models.ForeignKey('TechnicianPayout', on_delete=models.SET_NULL, null=True, blank=True, related_name='commissions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.booking.enquiry_id} - Tech: {self.technician_amount}"


class TechnicianPayout(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
    ]
    reference_id = models.CharField(max_length=40, unique=True)
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payouts')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=40, default='bank_transfer')
    transaction_reference = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_payouts')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.reference_id:
            self.reference_id = f"PO-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)


class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('operations', 'Operations'),
        ('marketing', 'Marketing'),
        ('salaries', 'Staff & Salaries'),
        ('equipment', 'Tools & Equipment'),
        ('office', 'Office & Utilities'),
        ('other', 'Other'),
    ]
    title = models.CharField(max_length=150)
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default='operations')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    expense_date = models.DateField()
    description = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-expense_date', '-created_at']


class TransactionLedger(models.Model):
    """Immutable financial audit ledger."""
    ENTRY_TYPE_CHOICES = [
        ('payment_in', 'Customer Payment'),
        ('refund_out', 'Customer Refund'),
        ('commission_split', 'Commission Split'),
        ('payout_out', 'Technician Payout'),
        ('expense_out', 'Business Expense'),
        ('adjustment', 'Manual Adjustment'),
    ]
    reference_id = models.CharField(max_length=50, db_index=True)
    entry_type = models.CharField(max_length=30, choices=ENTRY_TYPE_CHOICES, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    booking = models.ForeignKey('bookings.Booking', on_delete=models.SET_NULL, null=True, blank=True)
    responsible_admin = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError('TransactionLedger entries are immutable and cannot be modified.')
        super().save(*args, **kwargs)
