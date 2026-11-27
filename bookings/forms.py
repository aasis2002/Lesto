from django import forms
from django.utils import timezone
from services.models import ServiceArea, ServiceSubcategory
from .models import Complaint, JobUpdate, Review


class WhatsAppBookingForm(forms.Form):
    customer_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your full name'})
    )
    customer_phone = forms.CharField(
        max_length=25,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+977 98...'})
    )
    customer_whatsapp = forms.CharField(
        max_length=25,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'WhatsApp number (if different)'})
    )
    subcategory = forms.ModelChoiceField(
        queryset=ServiceSubcategory.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    service_area = forms.ModelChoiceField(
        queryset=ServiceArea.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    city = forms.CharField(
        max_length=80,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City (e.g. Kathmandu)'})
    )
    address = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'House no, street, landmark'})
    )
    preferred_date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    preferred_time = forms.CharField(
        max_length=40,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. 10:30 AM or Morning',
            'id': 'id_preferred_time',
        })
    )
    description = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Describe the issue or specific requirements...'})
    )
    photo = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, service=None, **kwargs):
        super().__init__(*args, **kwargs)
        if service is not None:
            self.fields['subcategory'].queryset = ServiceSubcategory.objects.filter(
                category=service.category, is_active=True
            )
            if service.subcategory_id:
                self.fields['subcategory'].initial = service.subcategory_id


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['service_rating', 'technician_rating', 'comment', 'photo']
        widgets = {
            'service_rating': forms.Select(choices=[(i, f'{i} Stars') for i in range(5, 0, -1)], attrs={'class': 'form-select'}),
            'technician_rating': forms.Select(choices=[(i, f'{i} Stars') for i in range(5, 0, -1)], attrs={'class': 'form-select'}),
            'comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Share your experience...'}),
            'photo': forms.FileInput(attrs={'class': 'form-control'}),
        }


class ComplaintForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ['subject', 'description']
        widgets = {
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brief issue summary'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Describe your complaint...'}),
        }


class JobUpdateForm(forms.ModelForm):
    class Meta:
        model = JobUpdate
        fields = ['note', 'is_completion_report', 'requested_material_amount']
        widgets = {
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Add job progress note or completion report...'}),
            'is_completion_report': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'requested_material_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }
