from pathlib import Path

from django import forms
from django.utils.text import slugify

from .ingest import SUPPORTED_EXTENSIONS
from .models import Topic


class TopicForm(forms.ModelForm):
    class Meta:
        model = Topic
        fields = ['name', 'description']
        widgets = {
            'description': forms.Textarea(
                attrs={'rows': 4, 'placeholder': 'Ex.: Leis, decretos, Constituição Federal, LGPD, CLT...'}
            ),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        slug = slugify(name)
        if not slug:
            raise forms.ValidationError('Use letras ou números no nome.')
        if Topic.objects.filter(slug=slug).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Já existe um tópico com esse nome.')
        return name


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={'accept': ','.join(SUPPORTED_EXTENSIONS)}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        clean_single = super().clean
        if isinstance(data, (list, tuple)):
            return [clean_single(item, initial) for item in data]
        return [clean_single(data, initial)]


class DocumentUploadForm(forms.Form):
    files = MultipleFileField(label='Arquivos', help_text='PDF, DOCX, TXT ou MD. Pode selecionar vários.')

    def clean_files(self):
        files = self.cleaned_data['files']
        invalid = [f.name for f in files if Path(f.name).suffix.lower() not in SUPPORTED_EXTENSIONS]
        if invalid:
            raise forms.ValidationError(f'Formato não suportado: {", ".join(invalid)}')
        return files
