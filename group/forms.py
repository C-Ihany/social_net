from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Group
from regions import REGION_CHOICES


class GroupForm(forms.ModelForm):
    """Formulaire de création / édition d'un groupe."""

    class Meta:
        model = Group
        fields = ['name', 'category', 'region', 'description', 'cover', 'privacy', 'dina']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'gp-input',
                'placeholder': _('Nom du groupe'),
                'maxlength': 100,
                'autofocus': True,
            }),
            'description': forms.Textarea(attrs={
                'class': 'gp-input',
                'rows': 4,
                'placeholder': _('Décrivez votre groupe…'),
                'maxlength': 500,
            }),
            'category': forms.Select(attrs={'class': 'gp-input'}),
            'region':   forms.Select(attrs={'class': 'gp-input'}, choices=REGION_CHOICES),
            'privacy':  forms.Select(attrs={'class': 'gp-input'}),
            'dina': forms.Textarea(attrs={
                'class': 'gp-input',
                'rows': 6,
                'placeholder': _('Rédigez le Dina du groupe — règles, engagements et traditions de la communauté…'),
                'maxlength': 3000,
            }),
        }
        labels = {
            'name':     'Nom',
            'category': _('Catégorie'),
            'region':   'Pays ou région',
            'description': _('Description'),
            'cover':    'Image de couverture',
            'privacy':  'Confidentialité',
            'dina':     'Dina (charte communautaire)',
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 3:
            raise forms.ValidationError(_("Le nom doit contenir au moins 3 caractères."))
        return name
