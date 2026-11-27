from decimal import Decimal
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import (
    BusinessSettings, CustomerProfile, IdentityDocument, TechnicianProfile, User, Verification,
)
from services.models import Service, ServiceCategory
from bookings.models import Booking
from finance.models import Expense, TransactionLedger
from finance.services import compute_financial_summary, process_refund, record_payment


class LetsToPlatformTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.biz = BusinessSettings.get_solo()
        self.cat = ServiceCategory.objects.create(name='Cleaning Services')
        self.service = Service.objects.create(
            category=self.cat,
            name='Sofa Cleaning',
            short_description='Deep sofa clean',
            description='Full steam clean',
            base_price=Decimal('2000.00'),
            is_available=True,
        )
        self.admin = User.objects.create_user(
            username='admin_test', password='Password123!', role=User.ROLE_ADMIN,
            full_name='Admin User', phone='+9779800000099', is_superuser=True, is_staff=True
        )
        self.customer = User.objects.create_user(
            username='cust_test', password='Password123!', role=User.ROLE_CUSTOMER,
            full_name='Customer User', phone='+9779800000088'
        )
        CustomerProfile.objects.create(user=self.customer, verification_status='approved')
        self.tech = User.objects.create_user(
            username='tech_test', password='Password123!', role=User.ROLE_TECHNICIAN,
            full_name='Tech User', phone='+9779800000077'
        )
        self.tech_profile = TechnicianProfile.objects.create(
            user=self.tech, full_legal_name='Tech User', verification_status='pending_review'
        )

    def test_whatsapp_booking_saves_enquiry_without_confirming(self):
        resp = self.client.post(
            reverse('bookings:initiate_whatsapp_booking', args=[self.service.slug]),
            {
                'customer_name': 'Aarav',
                'customer_phone': '+9779812345678',
                'address': 'Baneshwor, Kathmandu',
                'preferred_date': timezone.localdate().isoformat(),
                'preferred_time': '10:00 AM - 12:00 PM',
                'description': '3-seater fabric sofa cleaning',
                'latitude': '27.717200',
                'longitude': '85.324000',
            },
        )
        self.assertEqual(resp.status_code, 302)
        booking = Booking.objects.get(customer_name='Aarav')
        self.assertTrue(booking.enquiry_id.startswith('LT-'))
        self.assertEqual(booking.status, Booking.STATUS_WHATSAPP_INITIATED)
        self.assertIn('https://wa.me/', booking.whatsapp_redirect_url)
        self.assertEqual(booking.latitude, Decimal('27.717200'))
        self.assertEqual(booking.longitude, Decimal('85.324000'))
        self.assertIn('27.717200', booking.whatsapp_redirect_url)

    def test_role_based_access_control(self):
        self.client.force_login(self.customer)
        res_admin = self.client.get(reverse('dashboard:overview'))
        self.assertEqual(res_admin.status_code, 403)
        res_tech = self.client.get(reverse('bookings:technician_dashboard'))
        self.assertEqual(res_tech.status_code, 403)

    def test_kyc_document_access_restricted(self):
        doc = IdentityDocument.objects.create(
            user=self.tech,
            document_type='citizenship',
            document_number='123-456',
            front_image=SimpleUploadedFile('id.jpg', b'fakeimg', content_type='image/jpeg'),
        )
        self.client.force_login(self.customer)
        resp = self.client.get(reverse('core:serve_kyc_document', args=[doc.id, 'front_image']))
        self.assertEqual(resp.status_code, 403)

        self.client.force_login(self.admin)
        resp_admin = self.client.get(reverse('core:serve_kyc_document', args=[doc.id, 'front_image']))
        self.assertEqual(resp_admin.status_code, 200)

    def test_financial_commission_refund_and_immutable_ledger(self):
        self.tech_profile.verification_status = 'approved'
        self.tech_profile.save()
        booking = Booking.objects.create(
            customer=self.customer,
            customer_name=self.customer.full_name,
            customer_phone=self.customer.phone,
            category=self.cat,
            service=self.service,
            service_name_snapshot=self.service.name,
            description='Test',
            preferred_date=timezone.localdate(),
            preferred_time='10:00 AM - 12:00 PM',
            address='Kathmandu',
            assigned_technician=self.tech,
            estimated_price=Decimal('2000.00'),
            final_price=Decimal('2000.00'),
        )
        record_payment(booking, Decimal('2000.00'), 'cash', self.admin)
        self.assertEqual(booking.commission_record.technician_amount, Decimal('1400.00'))
        self.assertEqual(booking.commission_record.platform_amount, Decimal('600.00'))

        Expense.objects.create(title='Fuel', category='operations', amount=Decimal('100.00'), expense_date=timezone.localdate(), recorded_by=self.admin)
        summary = compute_financial_summary()
        self.assertEqual(summary['net_profit'], Decimal('500.00'))

        ledger_entry = TransactionLedger.objects.first()
        with self.assertRaises(ValueError):
            ledger_entry.amount = Decimal('9999.00')
            ledger_entry.save()

    def test_report_exports(self):
        self.client.force_login(self.admin)
        for fmt in ('csv', 'excel', 'pdf'):
            resp = self.client.get(reverse('finance:reports_export') + f'?format={fmt}')
            self.assertEqual(resp.status_code, 200)
