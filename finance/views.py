import csv
import io
from decimal import Decimal
from django.contrib import messages
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from openpyxl import Workbook
from fpdf import FPDF
from core.models import User
from core.utils import admin_permission_required, log_admin_activity, notify_user
from bookings.models import Booking
from .models import (
    Expense, Payment, Refund, TechnicianCommission, TechnicianPayout, TransactionLedger,
)
from .services import (
    compute_financial_summary, create_and_pay_payout, process_refund, record_payment,
)


@admin_permission_required('can_manage_finance')
def financial_overview(request):
    start_date = request.GET.get('start_date') or None
    end_date = request.GET.get('end_date') or None
    summary = compute_financial_summary(start_date, end_date)
    ledger = TransactionLedger.objects.select_related('booking', 'responsible_admin')[:40]
    refunds = Refund.objects.select_related('booking', 'processed_by')[:15]
    return render(request, 'admin_panel/finance_overview.html', {
        'summary': summary,
        'ledger': ledger,
        'refunds': refunds,
        'start_date': start_date or '',
        'end_date': end_date or '',
    })


@admin_permission_required('can_manage_finance')
def payments_list(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        booking = get_object_or_404(Booking, enquiry_id=request.POST.get('enquiry_id'))
        if action == 'record_payment':
            amount = Decimal(request.POST.get('amount') or booking.final_price)
            method = request.POST.get('method', 'cash')
            tx_code = request.POST.get('transaction_code', '')
            notes = request.POST.get('notes', '')
            pay = record_payment(booking, amount, method, request.user, tx_code, notes)
            log_admin_activity(request.user, 'Recorded payment', 'Payment', pay.reference_id, f'{amount} via {method}', request)
            messages.success(request, f'Payment {pay.reference_id} recorded.')
        elif action == 'refund':
            amount = Decimal(request.POST.get('amount') or 0)
            reason = request.POST.get('reason', 'Customer refund')
            if amount > 0:
                ref = process_refund(booking, amount, reason, request.user)
                log_admin_activity(request.user, 'Processed refund', 'Refund', ref.pk, f'{amount}: {reason}', request)
                messages.success(request, 'Refund processed and logged in ledger.')
        return redirect('finance:payments_list')

    payments = Payment.objects.select_related('booking', 'customer', 'verified_by')
    unpaid_bookings = Booking.objects.filter(payment_status__in=['unpaid', 'partially_paid']).exclude(status=Booking.STATUS_CANCELLED)
    return render(request, 'admin_panel/payments_list.html', {
        'payments': payments[:60],
        'unpaid_bookings': unpaid_bookings[:30],
    })


@admin_permission_required('can_manage_finance')
def commissions_list(request):
    commissions = TechnicianCommission.objects.select_related('booking', 'technician', 'payout')
    return render(request, 'admin_panel/commissions_list.html', {'commissions': commissions[:100]})


@admin_permission_required('can_approve_payouts')
def payouts_list(request):
    if request.method == 'POST':
        tech_id = request.POST.get('technician_id')
        tech = get_object_or_404(User, pk=tech_id, role=User.ROLE_TECHNICIAN)
        method = request.POST.get('payment_method', 'bank_transfer')
        tx_ref = request.POST.get('transaction_reference', '')
        notes = request.POST.get('notes', '')
        payout = create_and_pay_payout(tech, request.user, method, tx_ref, notes)
        if payout:
            log_admin_activity(request.user, 'Approved & paid technician payout', 'TechnicianPayout', payout.reference_id, f'{payout.amount} to {tech.full_name}', request)
            notify_user(tech, f'Payout Completed: {payout.reference_id}', f'Your payout of {payout.amount} has been processed.', 'payout', '/technician/earnings/')
            messages.success(request, f'Payout {payout.reference_id} completed for {tech.full_name}.')
        else:
            messages.warning(request, 'No pending commission balance for this technician.')
        return redirect('finance:payouts_list')

    techs_with_pending = []
    for tech in User.objects.filter(role=User.ROLE_TECHNICIAN).select_related('technician_profile'):
        pending = TechnicianCommission.objects.filter(technician=tech, is_paid_out=False).aggregate(s=Sum('technician_amount'))['s'] or Decimal('0.00')
        if pending > 0:
            techs_with_pending.append({'technician': tech, 'pending_amount': pending})

    payouts = TechnicianPayout.objects.select_related('technician', 'approved_by')
    return render(request, 'admin_panel/payouts_list.html', {
        'techs_with_pending': techs_with_pending,
        'payouts': payouts[:60],
    })


@admin_permission_required('can_manage_finance')
def expenses_list(request):
    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        if action == 'create':
            exp = Expense.objects.create(
                title=request.POST.get('title', '').strip(),
                category=request.POST.get('category', 'operations'),
                amount=Decimal(request.POST.get('amount') or 0),
                expense_date=request.POST.get('expense_date') or timezone.localdate(),
                description=request.POST.get('description', ''),
                recorded_by=request.user,
            )
            TransactionLedger.objects.create(
                reference_id=f"EXP-{exp.pk}",
                entry_type='expense_out',
                amount=-exp.amount,
                responsible_admin=request.user,
                description=f"Expense: {exp.title} ({exp.get_category_display()})",
            )
            log_admin_activity(request.user, 'Recorded expense', 'Expense', exp.pk, f'{exp.title}: {exp.amount}', request)
            messages.success(request, 'Expense recorded.')
        elif action == 'delete':
            exp = get_object_or_404(Expense, pk=request.POST.get('expense_id'))
            exp.delete()
            messages.info(request, 'Expense deleted.')
        return redirect('finance:expenses_list')

    expenses = Expense.objects.select_related('recorded_by')
    total = expenses.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    return render(request, 'admin_panel/expenses_list.html', {'expenses': expenses, 'total_expenses': total})


@admin_permission_required('can_view_reports')
def reports_export(request):
    report_type = request.GET.get('type', 'bookings')
    fmt = request.GET.get('format', '')
    start_date = request.GET.get('start_date') or None
    end_date = request.GET.get('end_date') or None

    summary = compute_financial_summary(start_date, end_date)
    bookings = Booking.objects.select_related('category', 'service', 'assigned_technician').order_by('-created_at')
    if start_date:
        bookings = bookings.filter(created_at__date__gte=start_date)
    if end_date:
        bookings = bookings.filter(created_at__date__lte=end_date)

    if not fmt:
        return render(request, 'admin_panel/reports.html', {
            'summary': summary,
            'bookings_count': bookings.count(),
            'start_date': start_date or '',
            'end_date': end_date or '',
        })

    headers = ['Enquiry ID', 'Date', 'Customer', 'Phone', 'Service', 'Category', 'Technician', 'Status', 'Payment', 'Final Price']
    rows = [
        [
            b.enquiry_id,
            b.preferred_date.strftime('%Y-%m-%d'),
            b.customer_name,
            b.customer_phone,
            b.service_name_snapshot,
            b.category.name if b.category else '-',
            b.assigned_technician.full_name if b.assigned_technician else 'Unassigned',
            b.get_status_display(),
            b.get_payment_status_display(),
            str(b.final_price),
        ]
        for b in bookings[:500]
    ]

    if fmt == 'csv':
        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = f'attachment; filename="letsto_{report_type}_report.csv"'
        writer = csv.writer(resp)
        writer.writerow(headers)
        writer.writerows(rows)
        return resp

    if fmt == 'excel':
        wb = Workbook()
        ws = wb.active
        ws.title = 'LetsTo Report'
        ws.append(['LetsTo Home Services - Financial & Booking Summary'])
        ws.append(['Gross Revenue', str(summary['gross_revenue']), 'Net Profit', str(summary['net_profit'])])
        ws.append([])
        ws.append(headers)
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        resp = HttpResponse(buf.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="letsto_{report_type}_report.xlsx"'
        return resp

    if fmt == 'pdf':
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()
        pdf.set_font('Helvetica', 'B', 14)
        pdf.cell(0, 10, 'LetsTo Home Services - Business & Booking Report', ln=True)
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(
            0, 7,
            f"Gross Revenue: {summary['gross_revenue']} | Net Revenue: {summary['net_revenue']} | Expenses: {summary['total_expenses']} | Net Profit: {summary['net_profit']}",
            ln=True,
        )
        pdf.ln(3)
        col_widths = [26, 22, 34, 26, 38, 28, 30, 26, 22, 22]
        pdf.set_font('Helvetica', 'B', 8)
        for h, w in zip(headers, col_widths):
            pdf.cell(w, 7, h[:16], border=1)
        pdf.ln()
        pdf.set_font('Helvetica', '', 7.5)
        for r in rows[:80]:
            for val, w in zip(r, col_widths):
                pdf.cell(w, 6, str(val)[:18], border=1)
            pdf.ln()
        pdf_bytes = bytes(pdf.output())
        resp = HttpResponse(pdf_bytes, content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="letsto_{report_type}_report.pdf"'
        return resp

    return redirect('finance:reports_export')
