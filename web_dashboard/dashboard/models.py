# menu/models.py
from django.db import models

class ExternalUser(models.Model):
    id = models.AutoField(primary_key=True)
    matrix_id = models.TextField(unique=True)
    moodle_id = models.IntegerField()
    is_teacher = models.BooleanField(default=False)
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False  # Django no crea ni migra esta tabla
        db_table = 'users'  # nombre real de la tabla en la DB externa

    def __dict__(self):
        return {
            'id': self.id,
            'matrix_id': self.matrix_id,
            'moodle_id': self.moodle_id,
            'is_teacher': self.is_teacher,
            'registered_at': self.registered_at.isoformat(),
            'username': self.matrix_id.split(":")[0][1:]  # extrae el nombre de usuario del matrix_id
        }

    def __str__(self):
        return self.matrix_id

class Room(models.Model):
    id = models.AutoField(primary_key=True)
    room_id = models.TextField(unique=True)
    moodle_course_id = models.IntegerField()
    teacher_id = models.IntegerField()  # references your external users table
    shortcode = models.TextField()
    moodle_group = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    class Meta:
        managed = False  # Django no crea ni migra esta tabla
        db_table = 'rooms'
        constraints = [
            models.UniqueConstraint(fields=['teacher_id', 'shortcode'], name='unique_teacher_shortcode')
        ]
    
    def get_created_at_aware(self):
        """Return timezone-aware created_at, converting naive values if needed."""
        from django.utils import timezone
        if self.created_at and timezone.is_naive(self.created_at):
            return timezone.make_aware(self.created_at)
        return self.created_at or timezone.now()

    def __str__(self):
        return f"{self.shortcode} (course {self.moodle_course_id})"
    
class Reaction(models.Model):
    id = models.AutoField(primary_key=True)
    teacher_id = models.IntegerField()
    student_id = models.IntegerField()
    room_id = models.IntegerField()
    emoji = models.TextField()
    count = models.IntegerField(default=1)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'reactions'
        constraints = [
            models.UniqueConstraint(fields=['teacher_id', 'student_id', 'emoji'], name='unique_reaction')
        ]

    def __str__(self):
        return f"{self.emoji} x{self.count} (teacher={self.teacher_id}, student={self.student_id})"


class Question(models.Model):
    id = models.AutoField(primary_key=True)
    teacher_id = models.IntegerField()
    room_id = models.IntegerField(null=True)
    title = models.TextField(null=True, blank=True)
    body = models.TextField()
    qtype = models.TextField()  # stored as enum in PG; keep text here
    expected_answer = models.TextField(null=True, blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    manual_active = models.BooleanField(default=False)
    allow_multiple_submissions = models.BooleanField(default=False)
    allow_multiple_selections = models.BooleanField(default=False)
    close_on_first_correct = models.BooleanField(default=False)
    close_triggered = models.BooleanField(default=False)
    created_at = models.DateTimeField(null=True, auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'questions'

    def __str__(self):
        return self.title or f"Question {self.id}"


class QuestionOption(models.Model):
    id = models.AutoField(primary_key=True)
    question_id = models.IntegerField()
    option_key = models.TextField()
    text = models.TextField()
    is_correct = models.BooleanField(default=False)
    position = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'question_options'

    def __str__(self):
        return f"{self.option_key}: {self.text}"


class QuestionResponse(models.Model):
    id = models.AutoField(primary_key=True)
    question_id = models.IntegerField()
    student_id = models.IntegerField()
    option_id = models.IntegerField(null=True)
    answer_text = models.TextField(null=True)
    submitted_at = models.DateTimeField(null=True)
    is_graded = models.BooleanField(default=False)
    score = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    grader_id = models.IntegerField(null=True)
    feedback = models.TextField(null=True)
    response_version = models.IntegerField(default=1)
    late = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'question_responses'

    def __str__(self):
        return f"Response {self.id} (q={self.question_id}, student={self.student_id})"


class ResponseOption(models.Model):
    response_id = models.IntegerField()
    option_id = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'response_options'

    def __str__(self):
        return f"ResponseOption response={self.response_id} option={self.option_id}"


class TeacherAvailability(models.Model):
    id = models.AutoField(primary_key=True)
    teacher_id = models.IntegerField()
    day_of_week = models.TextField()  # stored as enum (weekday) in DB
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        managed = False
        db_table = 'teacher_availability'

    def __str__(self):
        return f"Availability teacher={self.teacher_id} {self.day_of_week} {self.start_time}-{self.end_time}"

