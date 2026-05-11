import datetime
"""Integration tests for top-level dashboard views.

Contains tests that verify the main dashboard page, room selection
and basic rendering with mocked Moodle and bot DB data.
"""
import datetime
from unittest import mock
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from dashboard.models import TeacherAvailability
from unittest import mock
from dashboard.tests.helpers.mocks import (
    dashboard_test_stack,
    patch_teacher_availability,
    MOCK_COURSES,
    DummyAvail,
)

class FakeManager:
    def __init__(self, initial=None):
        self._items = initial or []
    def using(self, alias):
        return self
    def filter(self, **kwargs):
        # Very naive filter by teacher_id and day_of_week
        tid = kwargs.get('teacher_id')
        day = kwargs.get('day_of_week')
        results = [a for a in self._items if (tid is None or a.teacher_id == tid) and (day is None or a.day_of_week == day)]
        return FakeQuerySet(results)
    def create(self, **kwargs):
        obj = DummyAvail(len(self._items)+1, kwargs['teacher_id'], kwargs['day_of_week'], kwargs['start_time'], kwargs['end_time'])
        self._items.append(obj)
        return obj
    def exclude(self, **kwargs):
        return FakeQuerySet(self._items)

class FakeQuerySet(list):
    def exclude(self, **kwargs):
        return self
    def order_by(self, *fields):
        # Ordering not important for tests; return self to allow chaining
        return self

# reuse DummyAvail from helpers.mocks

class AvailabilityViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='x')
        self.client.force_login(self.user)
        session = self.client.session
        session['teacher'] = {
            'id': 42,
            'matrix_id': '@test:example.org',
            'moodle_id': 999,
            'is_teacher': True,
            'registered_at': datetime.datetime.utcnow().isoformat(),
            'username': 'test'
        }
        session.save()

        # Composite patch stack for Moodle + models + executor
        self._stack = dashboard_test_stack()
        self._stack.__enter__()

    def tearDown(self):
        # Stop patchers if they exist
        if getattr(self, '_stack', None):
            self._stack.__exit__(None, None, None)

    def test_create_availability_success(self):
        fake_manager = FakeManager()
        with mock.patch.object(TeacherAvailability, 'objects', fake_manager):
            resp = self.client.post(reverse('dashboard:create_availability'), {
                'day_of_week': 'Monday',
                'start_time': '08:00',
                'end_time': '09:00',
            }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Intervalo creado correctamente.' in str(m) for m in resp.context['messages']))
        # Ensure slot was stored via fake manager
        self.assertEqual(len(fake_manager._items), 1)

    def test_create_availability_overlap_error(self):
        # Existing overlapping interval 08:30-09:30
        existing = DummyAvail(1, 42, 'Monday', datetime.time(8,30), datetime.time(9,30))
        fake_manager = FakeManager([existing])
        with mock.patch.object(TeacherAvailability, 'objects', fake_manager):
            resp = self.client.post(reverse('dashboard:create_availability'), {
                'day_of_week': 'Monday',
                'start_time': '08:00',
                'end_time': '09:00',
            })
        # Should not redirect; re-render schedule page with modal flag
        self.assertEqual(resp.status_code, 200)
        self.assertIn('create_availability_form', resp.context)
        form = resp.context['create_availability_form']
        self.assertTrue(form.errors)
        self.assertIn('show_create_availability_modal', resp.context)
        self.assertEqual(resp.context['show_create_availability_modal'], 'true')

    def test_dashboard_view_uses_mocked_moodle(self):
        resp = self.client.get(reverse('dashboard:dashboard'))
        self.assertEqual(resp.status_code, 200)
        courses = resp.context['courses']
        # Should reflect mocked courses length
        self.assertEqual(len(courses), len(MOCK_COURSES))
        shortnames = {c['shortname'] for c in courses}
        self.assertIn('COURSE1', shortnames)
        self.assertIn('COURSE2', shortnames)

    def test_dashboard_room_route_renders(self):
        resp = self.client.get(reverse('dashboard:dashboard_room', args=[1]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context.get('selected_page'), 'dashboard')

    def test_tutoring_schedule_view_renders(self):
        with patch_teacher_availability([]):
            resp = self.client.get(reverse('dashboard:tutoring_schedule'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context.get('selected_page'), 'schedule')
