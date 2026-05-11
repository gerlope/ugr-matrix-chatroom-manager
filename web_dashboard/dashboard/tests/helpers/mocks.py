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

from config import USERNAME

# Public API exported by this helpers module. Keeps test imports explicit.
__all__ = [
    'MOCK_COURSES', 'MOCK_GROUPS', 'MOCK_ENROLLED',
    'MOCK_MATRIX_MEMBERS',
    'moodle_patches', 'model_queryset_patches', 'matrix_patches',
    'patch_teacher_availability', 'patch_questions', 'dashboard_test_stack',
    'DummyAvail', 'DummyRoom', 'DummyQuestion', 'DummyQuestionOption', 'DummyQuestionResponse', 'DummyResponseOption', 'DummyStudent',
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

MOCK_MATRIX_MEMBERS = [
    '@student.one:example.org',
    '@student.two:example.org',
]


class _FakeMatrixBackend:
    def __init__(self):
        self._rooms = {}
        self._counter = 0

    def _room_state(self, room_id):
        state = self._rooms.get(room_id)
        if state is None:
            state = {
                'name': '',
                'topic': '',
                'members': list(MOCK_MATRIX_MEMBERS),
                'invited': [],
                'power_levels': {},
            }
            self._rooms[room_id] = state
        return state

    async def create_room(self, name='', topic=None, general_room_id=None, join_rule=None, allowed_room_ids=None):
        self._counter += 1
        room_id = f'!fake-room-{self._counter}:example.org'
        state = self._room_state(room_id)
        state['name'] = name or room_id
        state['topic'] = topic or ''
        if USERNAME:
            state['members'] = list(dict.fromkeys([USERNAME] + state['members']))
        if general_room_id:
            self._room_state(general_room_id)
        return room_id

    async def invite_all_members(self, room_id, matrix_ids):
        return None

    async def join_user_admin(self, room_id, user_id):
        state = self._room_state(room_id)
        if user_id not in state['members']:
            state['members'].append(user_id)
        if user_id in state['invited']:
            state['invited'].remove(user_id)

    async def set_user_power_level(self, room_id, user_id, level):
        state = self._room_state(room_id)
        state['power_levels'][user_id] = level

    async def ensure_room_name_prefixed(self, room_id, prefix):
        state = self._room_state(room_id)
        current = state['name'] or ''
        if current.startswith(prefix):
            return
        state['name'] = prefix.strip() if not current else prefix + current

    async def silence_room_members(self, room_id, bot_mxid=USERNAME):
        state = self._room_state(room_id)
        affected = 0
        for user_id in state['members']:
            if bot_mxid and user_id == bot_mxid:
                continue
            state['power_levels'][user_id] = -10
            affected += 1
        return affected

    async def cancel_pending_invites(self, room_id, bot_mxid=USERNAME):
        state = self._room_state(room_id)
        cancelled = 0
        for user_id in list(state['invited']):
            if bot_mxid and user_id == bot_mxid:
                continue
            state['invited'].remove(user_id)
            cancelled += 1
        return cancelled

    async def append_subgroup_link_to_topic(self, general_room_id, subgroup_room_id, shortcode):
        state = self._room_state(general_room_id)
        line = f'Subgrupo {shortcode}: https://matrix.to/#/{subgroup_room_id}'
        current = state['topic'] or ''
        if line in current:
            return
        state['topic'] = (current + '\n' + line).strip() if current else line

    async def remove_subgroup_link_from_topic(self, general_room_id, subgroup_room_id, shortcode):
        state = self._room_state(general_room_id)
        current = state['topic'] or ''
        if not current:
            return
        line = f'Subgrupo {shortcode}: https://matrix.to/#/{subgroup_room_id}'
        lines = [entry for entry in current.splitlines() if entry.strip() and entry.strip() != line]
        state['topic'] = '\n'.join(lines)

    def fetch_matrix_room_members(self, room_id):
        state = self._rooms.get(room_id)
        if state is None:
            return list(MOCK_MATRIX_MEMBERS)
        return list(state['members'])


_fake_matrix = _FakeMatrixBackend()


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
def matrix_patches():
    """Patch Matrix helpers so tests use deterministic in-memory data."""
    with mock.patch('dashboard.matrix_client.create_room', side_effect=_fake_matrix.create_room), \
         mock.patch('dashboard.matrix_client.invite_all_members', side_effect=_fake_matrix.invite_all_members), \
         mock.patch('dashboard.matrix_client.join_user_admin', side_effect=_fake_matrix.join_user_admin), \
         mock.patch('dashboard.matrix_client.set_user_power_level', side_effect=_fake_matrix.set_user_power_level), \
         mock.patch('dashboard.matrix_client.ensure_room_name_prefixed', side_effect=_fake_matrix.ensure_room_name_prefixed), \
         mock.patch('dashboard.matrix_client.silence_room_members', side_effect=_fake_matrix.silence_room_members), \
         mock.patch('dashboard.matrix_client.cancel_pending_invites', side_effect=_fake_matrix.cancel_pending_invites), \
         mock.patch('dashboard.matrix_client.append_subgroup_link_to_topic', side_effect=_fake_matrix.append_subgroup_link_to_topic), \
         mock.patch('dashboard.matrix_client.remove_subgroup_link_from_topic', side_effect=_fake_matrix.remove_subgroup_link_from_topic), \
         mock.patch('dashboard.matrix_client.fetch_matrix_room_members', side_effect=_fake_matrix.fetch_matrix_room_members), \
         mock.patch('dashboard.utils.fetch_matrix_room_members', side_effect=_fake_matrix.fetch_matrix_room_members), \
         mock.patch('dashboard.views.mc_create_room', side_effect=_fake_matrix.create_room), \
         mock.patch('dashboard.views.invite_all_members', side_effect=_fake_matrix.invite_all_members), \
         mock.patch('dashboard.views.join_user_admin', side_effect=_fake_matrix.join_user_admin), \
         mock.patch('dashboard.views.set_user_power_level', side_effect=_fake_matrix.set_user_power_level), \
         mock.patch('dashboard.views.ensure_room_name_prefixed', side_effect=_fake_matrix.ensure_room_name_prefixed), \
         mock.patch('dashboard.views.silence_room_members', side_effect=_fake_matrix.silence_room_members), \
         mock.patch('dashboard.views.cancel_pending_invites', side_effect=_fake_matrix.cancel_pending_invites), \
         mock.patch('dashboard.views.append_subgroup_link_to_topic', side_effect=_fake_matrix.append_subgroup_link_to_topic), \
         mock.patch('dashboard.views.remove_subgroup_link_from_topic', side_effect=_fake_matrix.remove_subgroup_link_from_topic):
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
        stack.enter_context(matrix_patches())
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
        self.room_id = f"!dummy-room-{id}:example.org"
        self.moodle_course_id = None
        self.active = True
        self.moodle_group = None

    def get_created_at_aware(self):
        import datetime

        return datetime.datetime(2024, 1, 1, 12, 0, 0)


class DummyQuestion:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        # default flags and fields
        self.manual_active = kwargs.get('manual_active', False)
        self.start_at = kwargs.get('start_at', None)
        self.end_at = kwargs.get('end_at', None)

    def save(self, using=None):
        if getattr(self, '_raise_on_save', False):
            raise Exception('save failed')

    def delete(self, using=None):
        if getattr(self, '_raise_on_delete', False):
            raise Exception('delete failed')


class DummyQuestionOption:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class DummyQuestionResponse:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class DummyResponseOption:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class DummyStudent:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
