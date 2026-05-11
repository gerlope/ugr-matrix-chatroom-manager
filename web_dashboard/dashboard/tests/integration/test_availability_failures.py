"""Integration tests for room availability flows and failure cases.

These tests exercise the dashboard endpoints that manage teacher
availability slots — ensuring validation, overlap detection and
error handling behave as expected when interacting with the views
and mocked external dependencies.
"""

import datetime
from unittest import mock
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from django.db import IntegrityError

from dashboard.tests.helpers.mocks import dashboard_test_stack, patch_teacher_availability, DummyAvail


class RoomAvailabilityFailureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ratester', password='x')
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
        self._stack = dashboard_test_stack()
        self._stack.__enter__()
        # Ensure TeacherAvailability queries are patched by default for these tests
        self._ta_patch = patch_teacher_availability([])
        self._ta_patch.__enter__()

    def tearDown(self):
        if getattr(self, '_stack', None):
            self._stack.__exit__(None, None, None)
        if getattr(self, '_ta_patch', None):
            self._ta_patch.__exit__(None, None, None)

    # --- Room creation failures -------------------------------------------------
    def test_create_room_invalid_form(self):
        # missing course_id -> invalid
        resp = self.client.post(reverse('dashboard:create_room'), {
            'shortcode': 'ABC'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('create_room_form', resp.context)
        self.assertIn('show_create_modal', resp.context)

    def test_create_room_duplicate_shortcode(self):
        # simulate IntegrityError with unique in message
        with mock.patch('dashboard.views.Room') as R:
            R.objects.using.return_value.create.side_effect = IntegrityError('unique constraint')
            resp = self.client.post(reverse('dashboard:create_room'), {
                'course_id': '10',
                'shortcode': 'DUP',
            })
        self.assertEqual(resp.status_code, 200)
        form = resp.context['create_room_form']
        self.assertIn('shortcode', form.errors)

    def test_create_room_db_exception(self):
        with mock.patch('dashboard.views.Room') as R:
            R.objects.using.return_value.create.side_effect = Exception('boom')
            resp = self.client.post(reverse('dashboard:create_room'), {
                'course_id': '11',
                'shortcode': 'ERR',
            })
        self.assertEqual(resp.status_code, 200)
        form = resp.context['create_room_form']
        self.assertTrue(form.non_field_errors())

    # --- Availability create/edit/delete failures --------------------------------
    def test_create_availability_invalid_form(self):
        # end before start
        resp = self.client.post(reverse('dashboard:create_availability'), {
            'day_of_week': 'Monday',
            'start_time': '10:00',
            'end_time': '09:00',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('create_availability_form', resp.context)
        self.assertIn('show_create_availability_modal', resp.context)

    def test_create_availability_db_exception(self):
        with mock.patch('dashboard.views.TeacherAvailability') as TA:
            TA.objects.using.return_value.create.side_effect = Exception('db fail')
            resp = self.client.post(reverse('dashboard:create_availability'), {
                'day_of_week': 'Tuesday',
                'start_time': '08:00',
                'end_time': '09:00',
            })
        # should redirect to tutoring schedule even on exception
        self.assertEqual(resp.status_code, 302)

    def test_edit_availability_invalid_id(self):
        resp = self.client.post(reverse('dashboard:edit_availability'), {
            'avail_id': 'notint',
            'start_time': '08:00',
            'end_time': '09:00',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('ID de disponibilidad inválido' in str(m) for m in resp.context['messages']))

    def test_edit_availability_not_found(self):
        with mock.patch('dashboard.views.TeacherAvailability') as TA:
            TA.objects.using.return_value.filter.return_value.first.return_value = None
            resp = self.client.post(reverse('dashboard:edit_availability'), {
                'avail_id': '1',
                'start_time': '08:00',
                'end_time': '09:00',
            }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Disponibilidad no encontrada' in str(m) for m in resp.context['messages']))

    def test_edit_availability_permission(self):
        a = DummyAvail(1, teacher_id=999, day_of_week='Monday', start_time=datetime.time(8,0), end_time=datetime.time(9,0))
        with mock.patch('dashboard.views.TeacherAvailability') as TA:
            TA.objects.using.return_value.filter.return_value.first.return_value = a
            resp = self.client.post(reverse('dashboard:edit_availability'), {
                'avail_id': '1',
                'start_time': '08:30',
                'end_time': '09:30',
            }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('No tienes permiso para editar esta disponibilidad' in str(m) for m in resp.context['messages']))

    def test_edit_availability_form_invalid(self):
        a = DummyAvail(2, teacher_id=42, day_of_week='Monday', start_time=datetime.time(8,0), end_time=datetime.time(9,0))
        with mock.patch('dashboard.views.TeacherAvailability') as TA:
            TA.objects.using.return_value.filter.return_value.first.return_value = a
            resp = self.client.post(reverse('dashboard:edit_availability'), {
                'avail_id': '2',
                'start_time': '09:00',
                'end_time': '09:00',
            })
        # Should re-render schedule via _render_schedule; status 200 and modal flag
        self.assertEqual(resp.status_code, 200)
        self.assertIn('edit_availability_form', resp.context)
        self.assertIn('show_edit_availability_modal', resp.context)

    def test_edit_availability_overlap(self):
        a = DummyAvail(3, teacher_id=42, day_of_week='Monday', start_time=datetime.time(8,0), end_time=datetime.time(9,0))
        with mock.patch('dashboard.views.TeacherAvailability') as TA, \
             mock.patch('dashboard.views.check_availability_overlap', return_value=a):
            TA.objects.using.return_value.filter.return_value.first.return_value = a
            resp = self.client.post(reverse('dashboard:edit_availability'), {
                'avail_id': '3',
                'start_time': '08:30',
                'end_time': '09:30',
            })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('edit_availability_form', resp.context)
        self.assertIn('show_edit_availability_modal', resp.context)

    def test_edit_availability_save_exception(self):
        a = DummyAvail(4, teacher_id=42, day_of_week='Monday', start_time=datetime.time(8,0), end_time=datetime.time(9,0))
        a._raise = True
        with mock.patch('dashboard.views.TeacherAvailability') as TA:
            TA.objects.using.return_value.filter.return_value.first.return_value = a
            resp = self.client.post(reverse('dashboard:edit_availability'), {
                'avail_id': '4',
                'start_time': '08:30',
                'end_time': '09:30',
            }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Error al actualizar el intervalo' in str(m) for m in resp.context['messages']))

    def test_edit_availability_success(self):
        a = DummyAvail(7, teacher_id=42, day_of_week='Monday', start_time=datetime.time(8,0), end_time=datetime.time(9,0))
        with mock.patch('dashboard.views.TeacherAvailability') as TA, \
             mock.patch('dashboard.views.check_availability_overlap', return_value=None):
            TA.objects.using.return_value.filter.return_value.first.return_value = a
            resp = self.client.post(reverse('dashboard:edit_availability'), {
                'avail_id': '7',
                'start_time': '08:30',
                'end_time': '09:30',
            }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Intervalo actualizado correctamente.' in str(m) for m in resp.context['messages']))
        self.assertEqual(a.start_time, datetime.time(8, 30))
        self.assertEqual(a.end_time, datetime.time(9, 30))

    def test_delete_availability_invalid_id(self):
        resp = self.client.post(reverse('dashboard:delete_availability'), {'avail_id': 'bad'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('ID de disponibilidad inválido' in str(m) for m in resp.context['messages']))

    def test_delete_availability_not_found(self):
        with mock.patch('dashboard.views.TeacherAvailability') as TA:
            TA.objects.using.return_value.filter.return_value.first.return_value = None
            resp = self.client.post(reverse('dashboard:delete_availability'), {'avail_id': '10'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Disponibilidad no encontrada' in str(m) for m in resp.context['messages']))

    def test_delete_availability_permission(self):
        a = DummyAvail(5, teacher_id=999, day_of_week='Monday', start_time=datetime.time(8,0), end_time=datetime.time(9,0))
        with mock.patch('dashboard.views.TeacherAvailability') as TA:
            TA.objects.using.return_value.filter.return_value.first.return_value = a
            resp = self.client.post(reverse('dashboard:delete_availability'), {'avail_id': '5'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('No tienes permiso para eliminar esta disponibilidad' in str(m) for m in resp.context['messages']))

    def test_delete_availability_delete_exception(self):
        a = DummyAvail(6, teacher_id=42, day_of_week='Monday', start_time=datetime.time(8,0), end_time=datetime.time(9,0))
        a._raise = True
        with mock.patch('dashboard.views.TeacherAvailability') as TA:
            TA.objects.using.return_value.filter.return_value.first.return_value = a
            resp = self.client.post(reverse('dashboard:delete_availability'), {'avail_id': '6'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Error al eliminar la disponibilidad' in str(m) for m in resp.context['messages']))

    def test_delete_availability_success(self):
        a = mock.MagicMock()
        a.teacher_id = 42
        with mock.patch('dashboard.views.TeacherAvailability') as TA:
            TA.objects.using.return_value.filter.return_value.first.return_value = a
            resp = self.client.post(reverse('dashboard:delete_availability'), {'avail_id': '7'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Intervalo eliminado correctamente.' in str(m) for m in resp.context['messages']))
        a.delete.assert_called_with(using='bot_db')
