"""Reusable test mocks and patch helpers for the dashboard app.

Centralizes repetitive patch logic used across tests so individual test
cases remain focused on assertions.

Provided helpers:
 - moodle_patches(): context manager that patches Moodle fetch helpers.
 - model_queryset_patches(): patches Room & Reaction queryset access to avoid unmanaged DB hits.
 - synchronous_executor(): replaces ThreadPoolExecutor with a synchronous version.
 - patch_teacher_availability(existing): patches TeacherAvailability queryset to yield ``existing`` list items.
 - patch_questions(data): patches Question/QuestionOption/QuestionResponse/ResponseOption/ExternalUser for question assembly logic.

Usage example:

    from dashboard.tests.helpers.mocks import dashboard_test_stack, patch_teacher_availability
    with dashboard_test_stack():
        # all Moodle + model patches active
        ... run code ...

Or inside setUp:
    self.stack = dashboard_test_stack()
    self.stack.__enter__()
    self.addCleanup(self.stack.__exit__)

The individual helpers can be composed manually using contextlib.ExitStack.
"""

from contextlib import contextmanager, ExitStack
from unittest import mock

# Public API exported by this helpers module. Keeps test imports explicit.
__all__ = [
    'MOCK_COURSES', 'MOCK_GROUPS', 'MOCK_ENROLLED',
    'moodle_patches', 'model_queryset_patches', 'synchronous_executor',
    'patch_teacher_availability', 'patch_questions', 'dashboard_test_stack',
    'DummyAvail', 'DummyRoom', 'DummyQuestion',
]

MOCK_COURSES = [
    {'id': 101, 'shortname': 'COURSE1', 'fullname': 'Course 1', 'displayname': 'Course 1'},
    {'id': 102, 'shortname': 'COURSE2', 'fullname': 'Course 2', 'displayname': 'Course 2'},
]

MOCK_GROUPS = [
    {'id': 201, 'name': 'Group A'},
    {'id': 202, 'name': 'Group B'},
]

MOCK_ENROLLED = [
    {
        'id': 9001,
        'fullname': 'Student One',
        'roles': [{'shortname': 'student'}],
        'groups': [{'id': 201, 'name': 'Group A'}],
    },
    {
        'id': 9002,
        'fullname': 'Student Two',
        'roles': [{'shortname': 'student'}],
        'groups': [],
    },
]


@contextmanager
def moodle_patches(courses=None, groups=None, enrolled=None):
    """Patch Moodle fetch helpers with provided or default mock data."""
    courses = courses if courses is not None else MOCK_COURSES
    groups = groups if groups is not None else MOCK_GROUPS
    enrolled = enrolled if enrolled is not None else MOCK_ENROLLED
    with mock.patch('dashboard.utils.fetch_moodle_courses', return_value=courses), \
         mock.patch('dashboard.utils.fetch_moodle_groups', return_value=groups), \
         mock.patch('dashboard.utils.fetch_enrolled_students', return_value=enrolled):
        yield


@contextmanager
def model_queryset_patches():
    """Patch Room & Reaction queryset access to avoid DB usage in tests."""
    with mock.patch('dashboard.utils.Room') as room_mock, \
         mock.patch('dashboard.utils.Reaction') as reaction_mock:
        room_mock.objects.using.return_value.filter.return_value = []
        reaction_mock.objects.using.return_value.filter.return_value = []
        yield


@contextmanager
def synchronous_executor():
    """Replace ThreadPoolExecutor with a deterministic synchronous executor."""
    class _DummyFuture:
        def __init__(self, fn, *args, **kwargs):
            self._result = fn(*args, **kwargs)
        def result(self):
            return self._result
    class _DummyExecutor:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def submit(self, fn, *args, **kwargs):
            return _DummyFuture(fn, *args, **kwargs)
    with mock.patch('dashboard.utils.ThreadPoolExecutor', _DummyExecutor):
        yield


@contextmanager
def patch_teacher_availability(existing):
    """Patch TeacherAvailability queryset to yield provided existing items.

    ``existing`` should be an iterable of objects with day_of_week/start_time/end_time.
    """
    class FakeQS(list):
        def exclude(self, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
    def fake_filter(**kwargs):
        day = kwargs.get('day_of_week')
        if day:
            return FakeQS([e for e in existing if getattr(e, 'day_of_week', None) == day])
        return FakeQS(existing)
    # Patch both `dashboard.utils` and `dashboard.views` references so
    # modules that imported the model earlier get the fake queryset behavior.
    with mock.patch('dashboard.utils.TeacherAvailability') as TA, \
         mock.patch('dashboard.views.TeacherAvailability') as TA2:
        TA.objects.using.return_value.filter.side_effect = fake_filter
        TA2.objects.using.return_value.filter.side_effect = fake_filter
        yield


@contextmanager
def patch_questions(data):
    """Patch question-related models for ``assemble_questions_for_room``.

    ``data`` dict keys:
        questions: list of question objs (must have id, manual_active, start_at, end_at, room_id)
        options: list of option objs (id, question_id, position)
        responses: list of response objs (id, question_id, student_id, option_id, answer_text, submitted_at, score)
        response_options: list of objs (response_id, option_id) for multi-answer mapping
        students: list of student objs (id)
    Each object can be a simple namespace or dummy class with attributes.
    """
    class _QS(list):
        def order_by(self, *fields):
            return self
        def filter(self, **kwargs):  # allow chaining filter on objects mock
            return self
        def values(self, *fields):
            # Return list of dicts with requested fields to emulate QuerySet.values()
            out = []
            for obj in self:
                row = {}
                for f in fields:
                    # support attribute names directly
                    row[f] = getattr(obj, f, None)
                out.append(row)
            return out

    questions = data.get('questions', [])
    options = data.get('options', [])
    responses = data.get('responses', [])
    response_options = data.get('response_options', [])
    students = data.get('students', [])

    def _question_filter(**kwargs):
        room_id = kwargs.get('room_id')
        result = [q for q in questions if getattr(q, 'room_id', None) == room_id]
        return _QS(result)
    def _option_filter(**kwargs):
        qids = kwargs.get('question_id__in', [])
        result = [o for o in options if getattr(o, 'question_id', None) in qids]
        return _QS(result)
    def _response_filter(**kwargs):
        qids = kwargs.get('question_id__in', [])
        result = [r for r in responses if getattr(r, 'question_id', None) in qids]
        return _QS(result)
    def _resp_opts_filter(**kwargs):
        rids = kwargs.get('response_id__in', [])
        result = [ro for ro in response_options if getattr(ro, 'response_id', None) in rids]
        return _QS(result)
    def _students_filter(**kwargs):
        ids = kwargs.get('id__in', [])
        result = [s for s in students if getattr(s, 'id', None) in ids]
        return _QS(result)

    with mock.patch('dashboard.utils.Question') as Q, \
         mock.patch('dashboard.utils.QuestionOption') as QO, \
         mock.patch('dashboard.utils.QuestionResponse') as QR, \
         mock.patch('dashboard.utils.ResponseOption') as RO, \
         mock.patch('dashboard.utils.ExternalUser') as EU:
        Q.objects.using.return_value.filter.side_effect = _question_filter
        QO.objects.using.return_value.filter.side_effect = _option_filter
        QR.objects.using.return_value.filter.side_effect = _response_filter
        RO.objects.using.return_value.filter.side_effect = _resp_opts_filter
        EU.objects.using.return_value.filter.side_effect = _students_filter
        yield


@contextmanager
def dashboard_test_stack():
    """Composite context manager activating all standard dashboard mocks."""
    with ExitStack() as stack:
        stack.enter_context(moodle_patches())
        stack.enter_context(model_queryset_patches())
        stack.enter_context(synchronous_executor())
        yield


# Reusable dummy helpers used by multiple tests
class DummyAvail:
    def __init__(self, id, *args, **kwargs):
        """Flexible constructor to support multiple call styles:

        - DummyAvail(id, day_of_week, start_time, end_time)
        - DummyAvail(id, teacher_id, day_of_week, start_time, end_time)
        - DummyAvail(id, teacher_id=<int>, day_of_week=<str>, start_time=<time>, end_time=<time>)
        """
        self.id = id
        # kwargs-style construction (explicit names)
        if kwargs:
            self.teacher_id = kwargs.get('teacher_id')
            self.day_of_week = kwargs.get('day_of_week')
            self.start_time = kwargs.get('start_time')
            self.end_time = kwargs.get('end_time')
            return
        # positional construction
        if len(args) == 3:
            # (day_of_week, start_time, end_time)
            self.teacher_id = None
            self.day_of_week, self.start_time, self.end_time = args
        elif len(args) == 4:
            # (teacher_id, day_of_week, start_time, end_time)
            self.teacher_id, self.day_of_week, self.start_time, self.end_time = args
        else:
            raise TypeError('DummyAvail expects kwargs or 3/4 positional args')
    def delete(self, using=None):
        if getattr(self, '_raise', False):
            raise Exception('delete fail')
    def save(self, using=None):
        if getattr(self, '_raise', False):
            raise Exception('save fail')


class DummyRoom:
    def __init__(self, id):
        self.id = id
        self.shortcode = f"ROOM{id}"
        self.teacher_id = 42
        self.moodle_group = None


class DummyQuestion:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        # default flags
        self.manual_active = kwargs.get('manual_active', False)

    def save(self, using=None):
        if getattr(self, '_raise_on_save', False):
            raise Exception('save failed')

    def delete(self, using=None):
        if getattr(self, '_raise_on_delete', False):
            raise Exception('delete failed')
