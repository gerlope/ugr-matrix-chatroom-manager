import datetime
from unittest import mock
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from dashboard.tests.helpers.mocks import DummyRoom, dashboard_test_stack, DummyQuestion
"""Integration tests covering create/toggle/delete question failure paths.

These tests mock the `Room` and `Question` models and exercise
the create/delete/toggle endpoints to ensure proper error handling
and messaging for edge cases and exceptions.
"""

class QuestionFailureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qtester', password='x')
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
        # Activate general mocks for Moodle + models + executor
        self._stack = dashboard_test_stack()
        self._stack.__enter__()

    def tearDown(self):
        if getattr(self, '_stack', None):
            self._stack.__exit__(None, None, None)

    def test_create_question_form_invalid(self):
        # Missing required 'body' -> form invalid, should re-render with modal
        resp = self.client.post(reverse('dashboard:create_question'), {
            'selected_room_id': '1',
            'qtype': 'short_answer',
            # body omitted
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('create_question_form', resp.context)
        self.assertIn('show_create_question_modal', resp.context)

    def test_create_question_no_room_permission(self):
        # Patch Room to return a room owned by someone else
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 999
        fake_room.id = 7
        with mock.patch('dashboard.views.Room') as R:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '7',
                'qtype': 'short_answer',
                'title': 'No permission',
                'body': 'text',
            }, follow=True)
        # Should redirect back to dashboard with error message
        self.assertEqual(resp.status_code, 200)
        # messages may not always appear in resp.context; read from the request
        from django.contrib.messages import get_messages
        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any('No tienes permiso' in m for m in msgs))

    def test_create_question_multiple_choice_no_correct(self):
        # Patch Room to be owned by teacher
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 8
        with mock.patch('dashboard.views.Room') as R:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            # provide options but no correct flags
            post = {
                'selected_room_id': '8',
                'qtype': 'multiple_choice',
                'title': 'Choose one title',
                'body': 'Choose one',
                'option_0': 'A',
                'option_1': 'B',
            }
            resp = self.client.post(reverse('dashboard:create_question'), post)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('create_question_form', resp.context)
        # Expect non-field error about marking a correct option
        form = resp.context['create_question_form']
        self.assertTrue(form.non_field_errors())

    def test_create_question_db_exception(self):
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 9
        with mock.patch('dashboard.views.Room') as R, \
             mock.patch('dashboard.views.Question') as Q:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            Q.objects.using.return_value.create.side_effect = Exception('db create failed')
            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '9',
                'qtype': 'short_answer',
                'title': 'Answer title',
                'body': 'Answer',
            })
        self.assertEqual(resp.status_code, 200)
        form = resp.context['create_question_form']
        self.assertTrue(form.non_field_errors())

    def test_create_question_invalid_date_range(self):
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 10
        with mock.patch('dashboard.views.Room') as R:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '10',
                'qtype': 'short_answer',
                'title': 'Invalid dates',
                'body': 'Body',
                'start_at': '2026-05-11T12:00',
                'end_at': '2026-05-11T11:00',
            })

        self.assertEqual(resp.status_code, 200)
        self.assertIn('create_question_form', resp.context)
        form = resp.context['create_question_form']
        self.assertTrue(form.non_field_errors())
        self.assertIn('fecha de fin', str(form.non_field_errors()))

    def test_toggle_question_not_found(self):
        with mock.patch('dashboard.views.Question') as Q:
            Q.objects.using.return_value.filter.return_value.first.return_value = None
            resp = self.client.post(reverse('dashboard:toggle_question_active', args=[123]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Pregunta no encontrada' in str(m) for m in resp.context['messages']))

    def test_toggle_question_permission(self):
        q = DummyQuestion(id=5, teacher_id=99, room_id=1)
        with mock.patch('dashboard.views.Question') as Q:
            Q.objects.using.return_value.filter.return_value.first.return_value = q
            resp = self.client.post(reverse('dashboard:toggle_question_active', args=[5]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('No tienes permiso' in str(m) for m in resp.context['messages']))

    def test_toggle_question_closed_by_first_correct(self):
        q = DummyQuestion(id=6, teacher_id=42, room_id=2)
        q.close_on_first_correct = True
        q.close_triggered = True
        with mock.patch('dashboard.views.Question') as Q:
            Q.objects.using.return_value.filter.return_value.first.return_value = q
            resp = self.client.post(reverse('dashboard:toggle_question_active', args=[6]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('fue cerrada tras recibir la primera respuesta correcta' in str(m) for m in resp.context['messages']))

    def test_toggle_question_save_exception(self):
        q = DummyQuestion(id=7, teacher_id=42, room_id=3)
        q._raise_on_save = True
        with mock.patch('dashboard.views.Question') as Q:
            Q.objects.using.return_value.filter.return_value.first.return_value = q
            resp = self.client.post(reverse('dashboard:toggle_question_active', args=[7]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Error al actualizar la pregunta' in str(m) for m in resp.context['messages']))

    def test_delete_question_not_found(self):
        with mock.patch('dashboard.views.Question') as Q:
            Q.objects.using.return_value.filter.return_value.first.return_value = None
            resp = self.client.post(reverse('dashboard:delete_question', args=[999]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Pregunta no encontrada' in str(m) for m in resp.context['messages']))

    def test_delete_question_permission(self):
        q = DummyQuestion(id=8, teacher_id=99, room_id=4)
        with mock.patch('dashboard.views.Question') as Q:
            Q.objects.using.return_value.filter.return_value.first.return_value = q
            resp = self.client.post(reverse('dashboard:delete_question', args=[8]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('No tienes permiso para eliminar esta pregunta' in str(m) for m in resp.context['messages']))

    def test_delete_question_delete_exception(self):
        q = DummyQuestion(id=9, teacher_id=42, room_id=5)
        q._raise_on_delete = True
        with mock.patch('dashboard.views.Question') as Q:
            Q.objects.using.return_value.filter.return_value.first.return_value = q
            resp = self.client.post(reverse('dashboard:delete_question', args=[9]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any('Error al eliminar la pregunta' in str(m) for m in resp.context['messages']))


    def test_create_poll_success_and_options_not_correct(self):
        fake_q = DummyQuestion(id=111, teacher_id=42, room_id=5)
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 5
        with mock.patch('dashboard.views.Room') as R, \
            mock.patch('dashboard.views.Question') as Q, \
            mock.patch('dashboard.views.QuestionOption') as QO:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            Q.objects.using.return_value.create.return_value = fake_q
            # Track QuestionOption.create calls
            QO.objects.using.return_value.create = mock.MagicMock()

            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '5',
                'qtype': 'poll',
                'title': 'No permission',
                'body': 'text',
                'body': 'Which do you prefer?',
                'option_0': 'Tea',
                'option_1': 'Coffee',
            }, follow=False)            
            # Should redirect to dashboard with room_id param
            self.assertEqual(resp.status_code, 302)
            self.assertIn('room_id=5', resp['Location'])

            # Ensure QuestionOption.create was called for both options and with is_correct=False
            calls = QO.objects.using.return_value.create.call_args_list
            self.assertEqual(len(calls), 2)
            for call in calls:
                kwargs = call.kwargs
                self.assertIn('question_id', kwargs)
                self.assertIn('text', kwargs)
                self.assertFalse(kwargs.get('is_correct', True))

