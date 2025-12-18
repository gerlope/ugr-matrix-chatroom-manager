# menu/forms.py
from django import forms
import datetime

class ExternalLoginForm(forms.Form):
    username = forms.CharField(max_length=255)
    #password = forms.CharField(widget=forms.PasswordInput)

class CreateRoomForm(forms.Form):
    course_id = forms.IntegerField()
    shortcode = forms.CharField(max_length=100)
    topic = forms.CharField(max_length=200, required=False)
    moodle_group = forms.CharField(max_length=100, required=False)
    auto_invite = forms.BooleanField(required=False, initial=False, help_text="Invitar a todos los usuarios del grupo (admin join)")
    restrict_group = forms.BooleanField(required=False, initial=False, help_text="Limitar la sala al grupo seleccionado")


class CreateQuestionForm(forms.Form):
    title = forms.CharField(max_length=255, required=True)
    body = forms.CharField(widget=forms.Textarea, required=True)
    QTYPE_CHOICES = [
        ('multiple_choice', 'Opción múltiple'),
        ('poll', 'Encuesta'),
        ('true_false', 'Verdadero/Falso'),
        ('short_answer', 'Respuesta corta'),
        ('numeric', 'Numérica'),
        ('essay', 'Desarrollo'),
    ]
    qtype = forms.ChoiceField(choices=QTYPE_CHOICES)
    expected_answer = forms.CharField(max_length=500, required=False, help_text="Respuesta esperada (para preguntas de respuesta corta o numérica)")
    start_at = forms.DateTimeField(required=False, input_formats=['%Y-%m-%dT%H:%M'])
    end_at = forms.DateTimeField(required=False, input_formats=['%Y-%m-%dT%H:%M'])
    allow_multiple_answers = forms.BooleanField(required=False, initial=False)
    allow_multiple_submissions = forms.BooleanField(required=False, initial=False)
    close_on_first_correct = forms.BooleanField(required=False, initial=False, label='Cerrar tras primera correcta')


class CreateAvailabilityForm(forms.Form):
    WEEKDAY_CHOICES = [
        ('Monday', 'Lunes'), ('Tuesday', 'Martes'), ('Wednesday', 'Miércoles'),
        ('Thursday', 'Jueves'), ('Friday', 'Viernes'), ('Saturday', 'Sábado'), ('Sunday', 'Domingo')
    ]
    day_of_week = forms.ChoiceField(choices=WEEKDAY_CHOICES)
    start_time = forms.TimeField(input_formats=['%H:%M'])
    end_time = forms.TimeField(input_formats=['%H:%M'])

    def clean(self):
        cleaned = super().clean()
        st = cleaned.get('start_time')
        et = cleaned.get('end_time')
        if st and et and st >= et:
            raise forms.ValidationError('La hora de inicio debe ser anterior a la hora de fin.')
        # enforce timeline window 07:00-21:00
        earliest = datetime.time(hour=7, minute=0)
        latest = datetime.time(hour=21, minute=0)
        if st and st < earliest:
            raise forms.ValidationError('La hora de inicio no puede ser antes de las 07:00.')
        if et and et > latest:
            raise forms.ValidationError('La hora de fin no puede ser después de las 21:00.')
        return cleaned


class EditAvailabilityForm(forms.Form):
    start_time = forms.TimeField(input_formats=['%H:%M'])
    end_time = forms.TimeField(input_formats=['%H:%M'])

    def clean(self):
        cleaned = super().clean()
        st = cleaned.get('start_time')
        et = cleaned.get('end_time')
        if st and et and st >= et:
            raise forms.ValidationError('La hora de inicio debe ser anterior a la hora de fin.')
        # enforce timeline window 07:00-21:00
        earliest = datetime.time(hour=7, minute=0)
        latest = datetime.time(hour=21, minute=0)
        if st and st < earliest:
            raise forms.ValidationError('La hora de inicio no puede ser antes de las 07:00.')
        if et and et > latest:
            raise forms.ValidationError('La hora de fin no puede ser después de las 21:00.')
        return cleaned


class GradeResponseForm(forms.Form):
    score = forms.DecimalField(required=False, min_value=0, max_value=100, max_digits=6, decimal_places=2)
    feedback = forms.CharField(required=False, widget=forms.Textarea)