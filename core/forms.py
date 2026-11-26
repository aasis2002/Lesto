from django import forms
from django.contrib.auth.password_validation import validate_password
from .models import User, CustomerProfile, TechnicianProfile, Address, IdentityDocument
from services.models import ServiceCategory, ServiceArea


class LoginForm(forms.Form):
    identifier = forms.CharField(
        label='Phone Number, Username, or Email',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number, username, or email'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter password'})
    )


class CustomerRegistrationForm(forms.Form):
    full_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    phone = forms.CharField(max_length=25, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+97798...'}))
    whatsapp_number = forms.CharField(max_length=25, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Same as mobile if blank'}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    profile_photo = forms.ImageField(required=False, widget=forms.FileInput(attrs={'class': 'form-control'}))
    residential_address = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
    city = forms.CharField(max_length=80, widget=forms.TextInput(attrs={'class': 'form-control'}))
    district = forms.CharField(max_length=80, widget=forms.TextInput(attrs={'class': 'form-control'}))
    state = forms.CharField(max_length=80, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    postal_code = forms.CharField(max_length=20, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    document_type = forms.ChoiceField(choices=IdentityDocument.DOC_TYPE_CHOICES, required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    document_number = forms.CharField(max_length=80, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    front_image = forms.FileField(required=False, widget=forms.FileInput(attrs={'class': 'form-control'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if User.objects.filter(phone=phone).exists():
            raise forms.ValidationError('A user with this mobile number already exists.')
        return phone

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get('password')
        cpw = cleaned.get('confirm_password')
        if pw and cpw and pw != cpw:
            self.add_error('confirm_password', 'Passwords do not match.')
        if pw:
            validate_password(pw)
        return cleaned


class TechnicianRegistrationForm(forms.Form):
    full_legal_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    phone = forms.CharField(max_length=25, widget=forms.TextInput(attrs={'class': 'form-control'}))
    whatsapp_number = forms.CharField(max_length=25, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}))
    gender = forms.ChoiceField(
        choices=[('', 'Prefer not to say'), ('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    profile_photo = forms.ImageField(required=False, widget=forms.FileInput(attrs={'class': 'form-control'}))
    residential_address = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
    experience_years = forms.IntegerField(min_value=0, initial=1, widget=forms.NumberInput(attrs={'class': 'form-control'}))
    skills_summary = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'e.g. House wiring, MCB installation, inverter setup'}))
    previous_experience = forms.CharField(required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
    certificates_notes = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'CTEVT / Trade certificates'}))
    service_categories = forms.ModelMultipleChoiceField(
        queryset=ServiceCategory.objects.filter(is_active=True, is_deleted=False),
        widget=forms.CheckboxSelectMultiple()
    )
    service_areas = forms.ModelMultipleChoiceField(
        queryset=ServiceArea.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple()
    )
    emergency_contact_name = forms.CharField(max_length=120, widget=forms.TextInput(attrs={'class': 'form-control'}))
    emergency_contact_phone = forms.CharField(max_length=25, widget=forms.TextInput(attrs={'class': 'form-control'}))
    bank_name = forms.CharField(max_length=120, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    bank_account_name = forms.CharField(max_length=120, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    bank_account_number = forms.CharField(max_length=60, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    payout_wallet_id = forms.CharField(max_length=80, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'eSewa / Khalti ID'}))
    document_type = forms.ChoiceField(choices=IdentityDocument.DOC_TYPE_CHOICES, widget=forms.Select(attrs={'class': 'form-select'}))
    document_number = forms.CharField(max_length=80, widget=forms.TextInput(attrs={'class': 'form-control'}))
    front_image = forms.FileField(widget=forms.FileInput(attrs={'class': 'form-control'}))
    back_image = forms.FileField(required=False, widget=forms.FileInput(attrs={'class': 'form-control'}))
    certificate_file = forms.FileField(required=False, widget=forms.FileInput(attrs={'class': 'form-control'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if User.objects.filter(phone=phone).exists():
            raise forms.ValidationError('A user with this phone number already exists.')
        return phone

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get('password')
        cpw = cleaned.get('confirm_password')
        if pw and cpw and pw != cpw:
            self.add_error('confirm_password', 'Passwords do not match.')
        if pw:
            validate_password(pw)
        return cleaned


class KYCDocumentForm(forms.ModelForm):
    class Meta:
        model = IdentityDocument
        fields = ['document_type', 'document_number', 'front_image', 'back_image', 'address_proof', 'certificate_file']
        widgets = {
            'document_type': forms.Select(attrs={'class': 'form-select'}),
            'document_number': forms.TextInput(attrs={'class': 'form-control'}),
            'front_image': forms.FileInput(attrs={'class': 'form-control'}),
            'back_image': forms.FileInput(attrs={'class': 'form-control'}),
            'address_proof': forms.FileInput(attrs={'class': 'form-control'}),
            'certificate_file': forms.FileInput(attrs={'class': 'form-control'}),
        }


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ['label', 'full_address', 'landmark', 'city', 'district', 'state', 'postal_code', 'is_default']
        widgets = {
            'label': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Home / Office'}),
            'full_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'landmark': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'district': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
