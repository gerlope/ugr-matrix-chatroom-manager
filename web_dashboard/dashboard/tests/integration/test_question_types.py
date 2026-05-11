import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from dashboard.tests.helpers.mocks import DummyQuestion, DummyRoom, dashboard_test_stack


class QuestionTypeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qtypetest', password='x')
        self.client.force_login(self.user)
        session = self.client.session
        session['teacher'] = {
            'id': 42,
            'matrix_id': '@test:example.org',
            'moodle_id': 999,
            'is_teacher': True,
            'registered_at': datetime.datetime.utcnow().isoformat(),
            'username': 'test',
        }
        session.save()
        self._stack = dashboard_test_stack()
        self._stack.__enter__()

    def tearDown(self):
        if getattr(self, '_stack', None):
            self._stack.__exit__(None, None, None)

    def _patch_teacher_room(self, room_id):
        fake_room = DummyRoom(room_id)
        fake_room.id = room_id
        fake_room.teacher_id = 42
        return mock.patch('dashboard.views.Room', autospec=True), fake_room

    def _post_question(self, payload, room_id, question_return=None):
        fake_room = DummyRoom(room_id)
        fake_room.id = room_id
        fake_room.teacher_id = 42
        question_return = question_return or DummyQuestion(id=900, teacher_id=42, room_id=room_id)
        room_patch = mock.patch('dashboard.views.Room')
        question_patch = mock.patch('dashboard.views.Question')
        option_patch = mock.patch('dashboard.views.QuestionOption')
        with room_patch as R, question_patch as Q, option_patch as QO:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            Q.objects.using.return_value.create.return_value = question_return
            QO.objects.using.return_value.create = mock.MagicMock()
            response = self.client.post(reverse('dashboard:create_question'), payload, follow=False)
            return response, Q, QO

    def test_create_true_false_question(self):
        response, Q, QO = self._post_question({
            'selected_room_id': '10',
            'qtype': 'true_false',
            'title': 'Verdadero o falso',
            'body': 'The sky is blue',
            'option_0': 'Verdadero',
            'option_1': 'Falso',
            'tf_correct': '0',
        }, room_id=10)

        self.assertEqual(response.status_code, 302)
        self.assertIn('room_id=10', response['Location'])

        create_kwargs = Q.objects.using.return_value.create.call_args.kwargs
        self.assertEqual(create_kwargs['qtype'], 'true_false')
        self.assertIsNone(create_kwargs['expected_answer'])

        calls = QO.objects.using.return_value.create.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs['option_key'], 'V')
        self.assertEqual(calls[0].kwargs['text'], 'Verdadero')
        self.assertTrue(calls[0].kwargs['is_correct'])
        self.assertEqual(calls[1].kwargs['option_key'], 'F')
        self.assertEqual(calls[1].kwargs['text'], 'Falso')
        self.assertFalse(calls[1].kwargs['is_correct'])

    def test_create_poll_question(self):
        response, Q, QO = self._post_question({
            'selected_room_id': '11',
            'qtype': 'poll',
            'title': 'Encuesta',
            'body': 'Pick one',
            'option_0': 'Tea',
            'option_1': 'Coffee',
            'option_2': 'Water',
        }, room_id=11)

        self.assertEqual(response.status_code, 302)
        self.assertIn('room_id=11', response['Location'])

        create_kwargs = Q.objects.using.return_value.create.call_args.kwargs
        self.assertEqual(create_kwargs['qtype'], 'poll')
        self.assertIsNone(create_kwargs['expected_answer'])

        calls = QO.objects.using.return_value.create.call_args_list
        self.assertEqual(len(calls), 3)
        for idx, call in enumerate(calls):
            self.assertEqual(call.kwargs['option_key'], chr(65 + idx))
            self.assertFalse(call.kwargs['is_correct'])

    def test_create_short_answer_question_uses_expected_answer(self):
        response, Q, QO = self._post_question({
            'selected_room_id': '12',
            'qtype': 'short_answer',
            'title': 'Short answer',
            'body': 'What is 2+2?',
            'expected_answer': '4',
        }, room_id=12)

        self.assertEqual(response.status_code, 302)
        self.assertIn('room_id=12', response['Location'])

        create_kwargs = Q.objects.using.return_value.create.call_args.kwargs
        self.assertEqual(create_kwargs['qtype'], 'short_answer')
        self.assertEqual(create_kwargs['expected_answer'], '4')
        QO.objects.using.return_value.create.assert_not_called()

    def test_create_short_answer_question_without_expected_answer(self):
        response, Q, QO = self._post_question({
            'selected_room_id': '15',
            'qtype': 'short_answer',
            'title': 'Short answer without expected answer',
            'body': 'Explain your reasoning',
        }, room_id=15)

        self.assertEqual(response.status_code, 302)
        self.assertIn('room_id=15', response['Location'])

        create_kwargs = Q.objects.using.return_value.create.call_args.kwargs
        self.assertEqual(create_kwargs['qtype'], 'short_answer')
        self.assertIsNone(create_kwargs['expected_answer'])
        QO.objects.using.return_value.create.assert_not_called()

    def test_create_numeric_question_uses_expected_answer(self):
        response, Q, QO = self._post_question({
            'selected_room_id': '13',
            'qtype': 'numeric',
            'title': 'Numeric answer',
            'body': 'What is 3.14?',
            'expected_answer': '3.14',
        }, room_id=13)

        self.assertEqual(response.status_code, 302)
        self.assertIn('room_id=13', response['Location'])

        create_kwargs = Q.objects.using.return_value.create.call_args.kwargs
        self.assertEqual(create_kwargs['qtype'], 'numeric')
        self.assertEqual(create_kwargs['expected_answer'], '3.14')
        QO.objects.using.return_value.create.assert_not_called()

    def test_create_numeric_question_without_expected_answer(self):
        response, Q, QO = self._post_question({
            'selected_room_id': '16',
            'qtype': 'numeric',
            'title': 'Numeric without expected answer',
            'body': 'Provide a number',
        }, room_id=16)

        self.assertEqual(response.status_code, 302)
        self.assertIn('room_id=16', response['Location'])

        create_kwargs = Q.objects.using.return_value.create.call_args.kwargs
        self.assertEqual(create_kwargs['qtype'], 'numeric')
        self.assertIsNone(create_kwargs['expected_answer'])
        QO.objects.using.return_value.create.assert_not_called()

    def test_create_essay_question_does_not_use_expected_answer(self):
        response, Q, QO = self._post_question({
            'selected_room_id': '14',
            'qtype': 'essay',
            'title': 'Essay answer',
            'body': 'Write a short paragraph',
            'expected_answer': 'ignored',
        }, room_id=14)

        self.assertEqual(response.status_code, 302)
        self.assertIn('room_id=14', response['Location'])

        create_kwargs = Q.objects.using.return_value.create.call_args.kwargs
        self.assertEqual(create_kwargs['qtype'], 'essay')
        self.assertIsNone(create_kwargs['expected_answer'])
        QO.objects.using.return_value.create.assert_not_called()
