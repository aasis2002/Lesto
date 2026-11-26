import uuid
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from core.models import BusinessSettings
from bookings.models import Booking
from .models import (
    Expense, Payment, Refund, TechnicianCommission, TechnicianPayout, TransactionLedger,
)


def get_commission_rates(booking):
    """Returns (technician_rate, platform_rate) in Decimal percentages."""
    biz = BusinessSettings.get_solo()
    tech_rate = biz.default_technician_commission
    if booking.assigned_technician and hasattr(booking.assigned_technician, 'technician_profile'):
        custom = booking.assigned_technician.technician_profile.custom_commission_rate
        if custom is not None:
            tech_rate = custom
    elif booking.service and booking.service.technician_commission_rate is not None:
        tech_rate = booking.service.technician_commission_rate
    tech_rate = Decimal(tech_rate)
    platform_rate = Decimal('100.00') - tech_rate
    return tech_rate, platform_rate


@transaction.atomic
def record_payment(booking, amount, method, admin_user, transaction_code='', notes=''):
    amount = Decimal(amount)
    ref = f"PAY-{uuid.uuid4().hex[:8].upper()}"
    payment = Payment.objects.create(
        reference_id=ref,
        booking=booking,
        customer=booking.customer,
        amount=amount,
        method=method,
        status='paid',
        transaction_code=transaction_code,
        verified_by=admin_user,
        notes=notes,
    )
    TransactionLedger.objects.create(
        reference_id=ref,
        entry_type='payment_in',
        amount=amount,
        booking=booking,
        responsible_admin=admin_user,
        description=f"Customer payment ({method}) for booking {booking.enquiry_id}",
    )

    total_paid = booking.payments.filter(status='paid').aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    total_refunded = booking.refunds.filter(status='processed').aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    net_paid = total_paid - total_refunded

    if net_paid >= booking.final_price and booking.final_price > 0:
        booking.payment_status = 'paid'
        if booking.status in [Booking.STATUS_WORK_COMPLETED, Booking.STATUS_PAYMENT_PENDING]:
            booking.status = Booking.STATUS_PAYMENT_COMPLETED
    elif net_paid > 0:
        booking.payment_status = 'partially_paid'
    booking.payment_method = method
    booking.save(update_fields=['payment_status', 'payment_method', 'status', 'updated_at'])

    if booking.assigned_technician and booking.payment_status == 'paid':
        calculate_and_record_commission(booking, admin_user)
    return payment


@transaction.atomic
def calculate_and_record_commission(booking, admin_user=None):
    if not booking.assigned_technician:
        return None
    gross = Decimal(booking.final_price or 0)
    tech_rate, plat_rate = get_commission_rates(booking)
    tech_amt = (gross * tech_rate / Decimal('100.00')).quantize(Decimal('0.01'))
    plat_amt = (gross - tech_amt).quantize(Decimal('0.01'))

    existing = TechnicianCommission.objects.filter(booking=booking).first()
    if existing:
        if not existing.is_paid_out:
            existing.technician = booking.assigned_technician
            existing.gross_amount = gross
            existing.technician_rate = tech_rate
            existing.platform_rate = plat_rate
            existing.technician_amount = tech_amt
            existing.platform_amount = plat_amt
            existing.save()
        return existing

    comm = TechnicianCommission.objects.create(
        booking=booking,
        technician=booking.assigned_technician,
        gross_amount=gross,
        technician_rate=tech_rate,
        platform_rate=plat_rate,
        technician_amount=tech_amt,
        platform_amount=plat_amt,
    )
    TransactionLedger.objects.create(
        reference_id=f"COM-{booking.enquiry_id}",
        entry_type='commission_split',
        amount=tech_amt,
        booking=booking,
        responsible_admin=admin_user,
        description=f"Commission split for {booking.enquiry_id}: Tech {tech_rate}% ({tech_amt}), Platform {plat_rate}% ({plat_amt})",
    )
    return comm


@transaction.atomic
def process_refund(booking, amount, reason, admin_user):
    amount = Decimal(amount)
    refund = Refund.objects.create(
        booking=booking,
        amount=amount,
        reason=reason,
        status='processed',
        processed_by=admin_user,
    )
    TransactionLedger.objects.create(
        reference_id=f"REF-{refund.pk}-{booking.enquiry_id}",
        entry_type='refund_out',
        amount=-amount,
        booking=booking,
        responsible_admin=admin_user,
        description=f"Refund for {booking.enquiry_id}: {reason}",
    )
    booking.payment_status = 'refunded'
    booking.save(update_fields=['payment_status', 'updated_at'])
    return refund


@transaction.atomic
def create_and_pay_payout(technician, admin_user, payment_method='bank_transfer', transaction_reference='', notes=''):
    unpaid_comms = TechnicianCommission.objects.filter(technician=technician, is_paid_out=False)
    total_amt = unpaid_comms.aggregate(s=Sum('technician_amount'))['s'] or Decimal('0.00')
    if total_amt <= 0:
        return None
    payout = TechnicianPayout.objects.create(
        reference_id=f"PO-{uuid.uuid4().hex[:8].upper()}",
        technician=technician,
        amount=total_amt,
        payment_method=payment_method,
        transaction_reference=transaction_reference,
        status='paid',
        approved_by=admin_user,
        notes=notes,
        paid_at=timezone.now(),
    )
    unpaid_comms.update(is_paid_out=True, payout=payout)
    TransactionLedger.objects.create(
        reference_id=payout.reference_id,
        entry_type='payout_out',
        amount=-total_amt,
        responsible_admin=admin_user,
        description=f"Technician payout to {technician.full_name} ({payout.reference_id})",
    )
    return payout


def compute_financial_summary(start_date=None, end_date=None):
    pay_qs = Payment.objects.filter(status='paid')
    ref_qs = Refund.objects.filter(status='processed')
    exp_qs = Expense.objects.all()
    comm_qs = TechnicianCommission.objects.all()
    payout_qs = TechnicianPayout.objects.filter(status='paid')
    booking_qs = Booking.objects.exclude(status=Booking.STATUS_CANCELLED)

    if start_date:
        pay_qs = pay_qs.filter(paid_at__date__gte=start_date)
        ref_qs = ref_qs.filter(created_at__date__gte=start_date)
        exp_qs = exp_qs.filter(expense_date__gte=start_date)
        comm_qs = comm_qs.filter(created_at__date__gte=start_date)
        payout_qs = payout_qs.filter(paid_at__date__gte=start_date)
        booking_qs = booking_qs.filter(created_at__date__gte=start_date)
    if end_date:
        pay_qs = pay_qs.filter(paid_at__date__lte=end_date)
        ref_qs = ref_qs.filter(created_at__date__lte=end_date)
        exp_qs = exp_qs.filter(expense_date__lte=end_date)
        comm_qs = comm_qs.filter(created_at__date__lte=end_date)
        payout_qs = payout_qs.filter(paid_at__date__lte=end_date)
        booking_qs = booking_qs.filter(created_at__date__lte=end_date)

    gross_revenue = pay_qs.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    total_refunds = ref_qs.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    net_revenue = gross_revenue - total_refunds
    total_expenses = exp_qs.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    technician_commissions_total = comm_qs.aggregate(s=Sum('technician_amount'))['s'] or Decimal('0.00')
    platform_commission = comm_qs.aggregate(s=Sum('platform_amount'))['s'] or Decimal('0.00')
    technician_paid = payout_qs.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    outstanding_payouts = TechnicianCommission.objects.filter(is_paid_out=False).aggregate(
        s=Sum('technician_amount')
    )['s'] or Decimal('0.00')
    pending_payments = booking_qs.filter(payment_status__in=['unpaid', 'partially_paid']).aggregate(
        s=Sum('final_price')
    )['s'] or Decimal('0.00')
    net_profit = net_revenue - technician_commissions_total - total_expenses

    return {
        'gross_revenue': gross_revenue,
        'total_refunds': total_refunds,
        'net_revenue': net_revenue,
        'total_expenses': total_expenses,
        'technician_commissions_total': technician_commissions_total,
        'platform_commission': platform_commission,
        'technician_paid': technician_paid,
        'outstanding_payouts': outstanding_payouts,
        'pending_payments': pending_payments,
        'net_profit': net_profit,
    }
