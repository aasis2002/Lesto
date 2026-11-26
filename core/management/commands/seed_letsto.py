from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import (
    Address, AdminProfile, BusinessSettings, CustomerProfile, RolePermission,
    TechnicianProfile, User, Verification, WebsiteSettings,
)
from services.models import Service, ServiceArea, ServiceCategory, ServiceSubcategory
from bookings.models import Booking, BookingStatusHistory, JobAssignment, Review
from finance.models import Expense
from finance.services import record_payment


class Command(BaseCommand):
    help = 'Seed LetsTo Home Services platform with initial categories, services, users, and sample bookings.'

    def handle(self, *args, **options):
        WebsiteSettings.get_solo()
        BusinessSettings.get_solo()

        super_role, _ = RolePermission.objects.get_or_create(
            name='Super Administrator',
            defaults={
                'description': 'Full access to all platform operations and financials',
                'can_manage_bookings': True, 'can_manage_services': True,
                'can_manage_customers': True, 'can_manage_technicians': True,
                'can_verify_kyc': True, 'can_manage_finance': True,
                'can_approve_payouts': True, 'can_manage_settings': True,
                'can_manage_admins': True, 'can_view_reports': True,
                'can_view_audit_logs': True,
            },
        )

        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@letsto.com',
                'role': User.ROLE_ADMIN,
                'full_name': 'LetsTo Administrator',
                'phone': '+9779800000001',
                'whatsapp_number': '9779800000001',
                'is_staff': True,
                'is_superuser': True,
            },
        )
        if created:
            admin_user.set_password('Admin@12345')
            admin_user.save()
        AdminProfile.objects.get_or_create(
            user=admin_user,
            defaults={'department': 'Management', 'designation': 'Platform Director', 'role_permission': super_role},
        )

        # Service Areas: All major areas across Kathmandu, Lalitpur, and Bhaktapur
        kathmandu_areas = [
            'Anamnagar', 'Asan', 'Babarmahal', 'Bagbazar', 'Balaju', 'Balkhu', 'Baluwatar',
            'Banasthali', 'Bansbari', 'Basantapur', 'Battisputali', 'Boudha', 'Budhanilkantha',
            'Chabahil', 'Chakrapath', 'Chandragiri', 'Chobhar', 'Chundevi', 'Dakshinkali',
            'Dhapasi', 'Dhumbarahi', 'Dillibazar', 'Durbar Marg', 'Gaushala', 'Ghattekulo',
            'Gokarneshwor', 'Goldhunga', 'Gongabu', 'Gyaneshwor', 'Hattigauda', 'Hattisar',
            'Indra Chowk', 'Jadibuti', 'Jorpati', 'Kalanki', 'Kalimati', 'Kalopul', 'Kamaladi',
            'Kirtipur', 'Koteshwor', 'Kuleshwor', 'Lazimpat', 'Maharajgunj', 'Maitidevi',
            'Maitighar', 'Manamaiju', 'Mitrapark', 'Nagarjun', 'Naikap', 'Naxal', 'New Baneshwor',
            'New Road', 'Old Baneshwor', 'Panipokhari', 'Pepsicola', 'Pharping', 'Putalisadak',
            'Ramkot', 'Ratopul', 'Rudramati', 'Samakhusi', 'Sankhamul', 'Sankhu', 'Setopul',
            'Sifal', 'Sinamangal', 'Singha Durbar', 'Sitapaila', 'Sukedhara', 'Sundarijal',
            'Swoyambhu', 'Syuchatar', 'Tangal', 'Teku', 'Thamel', 'Thankot', 'Thapathali',
            'Tinkune', 'Tokha', 'Tripureshwor',
        ]
        lalitpur_areas = [
            'Badikhel', 'Bagdol', 'Balkumari', 'Bhaisepati', 'Bhanimandal', 'Bungamati',
            'Chakupat', 'Chapagaun', 'Chyasal', 'Dhapakhel', 'Dhobighat', 'Ekantakuna',
            'Godawari', 'Gwarko', 'Harisiddhi', 'Hattiban', 'Imadol', 'Jawalakhel',
            'Jhamsikhel', 'Khokana', 'Kumaripati', 'Kupondole', 'Kusunti', 'Lagankhel',
            'Lamatar', 'Lubhu', 'Mahalaxmisthan', 'Manbhawan', 'Mangalbazar', 'Nakhudol',
            'Nakhipot', 'Patan Dhoka', 'Patan Durbar Square', 'Pulchowk', 'Sainbu', 'Sanepa',
            'Satdobato', 'Shankhamul (Lalitpur)', 'Sunakothi', 'Sundhara (Patan)', 'Thaiba',
            'Thasikhel', 'Thecho', 'Tikathali',
        ]
        bhaktapur_areas = [
            'Bageshwori', 'Balkot', 'Bhaktapur Durbar Square', 'Bode', 'Byasi', 'Changunarayan',
            'Chyamasingh', 'Dadhikot', 'Dattatreya', 'Dekocha', 'Dudhpati', 'Duwakot',
            'Gatthaghar', 'Gundu', 'Jagati', 'Jhaukhel', 'Kamalbinayak', 'Katunje',
            'Kaushaltar', 'Liwali', 'Lokanthali', 'Madhyapur Thimi', 'Nagarkot', 'Nangkhel',
            'Nikoshera', 'Radhe Radhe', 'Sallaghari', 'Shankhadhar Chowk', 'Sipadol',
            'Sirutar', 'Sudal', 'Suryabinayak', 'Tathali', 'Taumadhi',
        ]

        area_rows = (
            [(a, 'Kathmandu', 'Kathmandu') for a in kathmandu_areas]
            + [(a, 'Lalitpur', 'Lalitpur') for a in lalitpur_areas]
            + [(a, 'Bhaktapur', 'Bhaktapur') for a in bhaktapur_areas]
        )
        areas = []
        for area_name, city, dist in area_rows:
            a, _ = ServiceArea.objects.get_or_create(name=area_name, city=city, defaults={'district': dist})
            areas.append(a)

        # Categories & Subcategories
        catalog = {
            'Cleaning Services': {
                'icon': 'sparkles',
                'desc': 'Professional residential and commercial cleaning by trained specialists.',
                'subs': [
                    'House Cleaning', 'Full Home Deep Cleaning', 'Kitchen Cleaning',
                    'Bathroom Cleaning', 'Toilet Cleaning', 'Washroom Cleaning',
                    'Sofa Cleaning', 'Carpet Cleaning', 'Office Cleaning',
                    'Commercial Cleaning', 'Water Tank Cleaning', 'Floor Cleaning',
                ],
                'services': [
                    ('Full Home Deep Cleaning', 'Complete top-to-bottom sanitization for apartments and houses.', 4500, 3999, '4 - 6 Hours', True, True),
                    ('Sofa & Upholstery Cleaning', 'Steam and vacuum extraction for fabric and leather sofas.', 1800, None, '1.5 - 2 Hours', True, True),
                    ('Kitchen & Chimney Degreasing', 'Deep oil & grease removal for kitchen tiles, cabinets, and chimney.', 2200, 1950, '2 - 3 Hours', True, False),
                    ('Water Tank Cleaning', 'Hygienic mechanized scrubbing and anti-bacterial tank sanitization.', 2500, None, '2 Hours', False, True),
                ],
            },
            'Electrical & Wiring Services': {
                'icon': 'zap',
                'desc': 'Certified electricians for safe installations, fault diagnostics, and wiring.',
                'subs': [
                    'House Wiring', 'Electrical Installation', 'Fan Installation',
                    'Switchboard Repair', 'Lighting Installation', 'Electrical Fault Repair',
                    'MCB Installation', 'Inverter Installation', 'Commercial Electrical Work',
                ],
                'services': [
                    ('Inverter & Battery Installation', 'Complete home backup inverter wiring and load testing.', 1500, None, '1 - 2 Hours', True, True),
                    ('Electrical Fault & Short-Circuit Repair', 'Rapid troubleshooting for tripping MCBs and power outages.', 800, None, '1 Hour', True, True),
                    ('Ceiling Fan & Chandelier Installation', 'Safe mounting and wiring for ceiling fans and decorative lights.', 700, 599, '1 Hour', False, True),
                ],
            },
            'Plumbing & Repair Services': {
                'icon': 'droplets',
                'desc': 'Leak detection, pipe fitting, drainage clearing, and bathroom installations.',
                'subs': [
                    'Bathroom Plumbing', 'Toilet Repair', 'Tap Installation',
                    'Water Leakage Repair', 'Pipe Installation', 'Water Tank Installation',
                    'Drainage Cleaning', 'Bathroom Fittings', 'Kitchen Plumbing',
                ],
                'services': [
                    ('Water Leakage & Pipe Repair', 'Concealed and exposed pipe leak sealing and replacement.', 900, None, '1 - 2 Hours', True, True),
                    ('Tap, Shower & Bathroom Fittings', 'Installation and replacement of mixers, taps, and commodes.', 750, None, '1 Hour', True, True),
                    ('Drainage & Sink Unclogging', 'High-pressure clearing for blocked kitchen and bathroom drains.', 1100, 950, '1 - 1.5 Hours', False, True),
                ],
            },
        }

        all_services = []
        all_cats = []
        for idx, (cat_name, cfg) in enumerate(catalog.items(), start=1):
            cat, _ = ServiceCategory.objects.get_or_create(
                name=cat_name,
                defaults={'icon_name': cfg['icon'], 'description': cfg['desc'], 'display_order': idx},
            )
            all_cats.append(cat)
            sub_map = {}
            for sub_name in cfg['subs']:
                sub, _ = ServiceSubcategory.objects.get_or_create(category=cat, name=sub_name)
                sub_map[sub_name] = sub

            for s_name, s_desc, base_p, promo_p, dur, feat, pop in cfg['services']:
                srv, _ = Service.objects.get_or_create(
                    name=s_name,
                    category=cat,
                    defaults={
                        'subcategory': sub_map.get(s_name),
                        'short_description': s_desc,
                        'description': f'{s_desc} Delivered by LetsTo KYC-verified professionals with 100% service guarantee.',
                        'whats_included': 'Site inspection\nProfessional tools & safety gear\nPost-work cleanup\n7-day service warranty',
                        'base_price': Decimal(base_p),
                        'promo_price': Decimal(promo_p) if promo_p else None,
                        'estimated_duration': dur,
                        'is_featured': feat,
                        'is_popular': pop,
                        'is_available': True,
                    },
                )
                srv.service_areas.set(areas)
                all_services.append(srv)

        # Sample Verified Technician
        tech_user, t_created = User.objects.get_or_create(
            username='+9779811111111',
            defaults={
                'email': 'ram.tech@letsto.com',
                'role': User.ROLE_TECHNICIAN,
                'full_name': 'Ram Bahadur Thapa',
                'phone': '+9779811111111',
                'whatsapp_number': '9779811111111',
            },
        )
        if t_created:
            tech_user.set_password('Tech@12345')
            tech_user.save()
        tp, _ = TechnicianProfile.objects.get_or_create(
            user=tech_user,
            defaults={
                'full_legal_name': 'Ram Bahadur Thapa',
                'residential_address': 'New Baneshwor, Kathmandu',
                'experience_years': 6,
                'skills_summary': 'Electrical Wiring, Inverter Setup, Plumbing & Deep Cleaning',
                'verification_status': 'approved',
                'average_rating': Decimal('4.90'),
            },
        )
        tp.service_categories.set(all_cats)
        tp.service_areas.set(areas)
        Verification.objects.get_or_create(user=tech_user, defaults={'status': 'approved', 'reviewed_by': admin_user, 'reviewed_at': timezone.now()})

        # Sample Customer
        cust_user, c_created = User.objects.get_or_create(
            username='+9779822222222',
            defaults={
                'email': 'sita.sharma@example.com',
                'role': User.ROLE_CUSTOMER,
                'full_name': 'Sita Sharma',
                'phone': '+9779822222222',
                'whatsapp_number': '9779822222222',
            },
        )
        if c_created:
            cust_user.set_password('Cust@12345')
            cust_user.save()
        CustomerProfile.objects.get_or_create(
            user=cust_user,
            defaults={'residential_address': 'Jhamsikhel, Lalitpur', 'city': 'Lalitpur', 'district': 'Lalitpur', 'verification_status': 'approved'},
        )
        Address.objects.get_or_create(
            user=cust_user, label='Home',
            defaults={'full_address': 'House 42, Jhamsikhel Road', 'city': 'Lalitpur', 'district': 'Lalitpur', 'is_default': True}
        )
        Verification.objects.get_or_create(user=cust_user, defaults={'status': 'approved', 'reviewed_by': admin_user, 'reviewed_at': timezone.now()})

        # Sample Bookings + Payment + Commission + Review + Expense
        if not Booking.objects.exists() and all_services:
            b1 = Booking.objects.create(
                customer=cust_user,
                customer_name=cust_user.full_name,
                customer_phone=cust_user.phone,
                customer_whatsapp=cust_user.whatsapp_number,
                category=all_services[0].category,
                service=all_services[0],
                service_name_snapshot=all_services[0].name,
                description='3BHK apartment full deep cleaning before family event.',
                preferred_date=timezone.localdate() - timedelta(days=2),
                preferred_time='10:00 AM - 12:00 PM',
                address='House 42, Jhamsikhel Road, Lalitpur',
                city='Lalitpur',
                assigned_technician=tech_user,
                estimated_price=all_services[0].effective_price,
                final_price=all_services[0].effective_price,
                status=Booking.STATUS_CLOSED,
                completed_at=timezone.now() - timedelta(days=1),
            )
            BookingStatusHistory.objects.create(booking=b1, to_status=Booking.STATUS_CLOSED, changed_by=admin_user, note='Completed & closed')
            JobAssignment.objects.create(booking=b1, technician=tech_user, assigned_by=admin_user, acceptance_status='accepted')
            record_payment(b1, b1.final_price, 'esewa', admin_user, 'ESW-998811', 'Seeded sample payment')
            Review.objects.create(
                booking=b1, customer=cust_user, technician=tech_user, service=all_services[0],
                service_rating=5, technician_rating=5,
                comment='Very punctual and thorough cleaning team! Highly recommended.'
            )

            Booking.objects.create(
                customer=cust_user,
                customer_name=cust_user.full_name,
                customer_phone=cust_user.phone,
                customer_whatsapp=cust_user.whatsapp_number,
                category=all_services[4].category,
                service=all_services[4],
                service_name_snapshot=all_services[4].name,
                description='Inverter tripping when AC turns on.',
                preferred_date=timezone.localdate() + timedelta(days=1),
                preferred_time='02:00 PM - 04:00 PM',
                address='House 42, Jhamsikhel Road, Lalitpur',
                city='Lalitpur',
                estimated_price=all_services[4].effective_price,
                final_price=all_services[4].effective_price,
                status=Booking.STATUS_WHATSAPP_INITIATED,
            )

            Expense.objects.create(
                title='Cleaning Chemicals & Supplies',
                category='equipment',
                amount=Decimal('1200.00'),
                expense_date=timezone.localdate() - timedelta(days=1),
                recorded_by=admin_user,
            )

        self.stdout.write(self.style.SUCCESS('LetsTo seed data created successfully!'))
