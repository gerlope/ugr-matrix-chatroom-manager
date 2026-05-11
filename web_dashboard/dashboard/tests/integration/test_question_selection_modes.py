"""Integration tests for multiple choice question selection modes.

Tests the behavior of switching between single-selection (radio) and
multi-selection (checkbox) for multiple choice questions, ensuring
correct answers are properly handled in each mode.
"""

import datetime
from unittest import mock
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from dashboard.tests.helpers.mocks import DummyRoom, dashboard_test_stack, DummyQuestion


class MultipleChoiceSelectionModeTests(TestCase):
    """Test single vs. multi-selection handling for multiple choice questions."""

    def setUp(self):
        self.user = User.objects.create_user(username='qmodetest', password='x')
        self.client.force_login(self.user)
        session = self.client.session
        session['teacher'] = {
            'id': 42,
            'matrix_id': '@teacher:example.org',
            'moodle_id': 1000,
            'is_teacher': True,
            'registered_at': datetime.datetime.utcnow().isoformat(),
            'username': 'teacher'
        }
        session.save()
        self._stack = dashboard_test_stack()
        self._stack.__enter__()

    def tearDown(self):
        if getattr(self, '_stack', None):
            self._stack.__exit__(None, None, None)

    def test_create_multiple_choice_radio_single_selection(self):
        """Test creating a single-selection (radio button) multiple choice question.
        
        When option_correct_single is set, only that option should be marked as correct.
        allow_multiple_selections should be False.
        """
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 1
        fake_q = DummyQuestion(id=100, teacher_id=42, room_id=1, allow_multiple_selections=False)
        
        with mock.patch('dashboard.views.Room') as R, \
             mock.patch('dashboard.views.Question') as Q, \
             mock.patch('dashboard.views.QuestionOption') as QO:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            Q.objects.using.return_value.create.return_value = fake_q
            QO.objects.using.return_value.create = mock.MagicMock()

            # Create with radio button: only option 1 is correct
            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '1',
                'qtype': 'multiple_choice',
                'title': 'Which is correct?',
                'body': 'Pick the right answer',
                'option_0': 'Wrong A',
                'option_1': 'Correct',
                'option_2': 'Wrong B',
                'option_correct_single': '1',  # Radio button: single choice mode
                'allow_multiple_selections': '',  # Not checked = False
            }, follow=False)
            
            # Verify question was created with allow_multiple_selections=False
            Q.objects.using.return_value.create.assert_called_once()
            call_kwargs = Q.objects.using.return_value.create.call_args[1]
            self.assertFalse(call_kwargs['allow_multiple_selections'])
            
            # Verify only one option (index 1) was marked as correct
            option_calls = QO.objects.using.return_value.create.call_args_list
            self.assertEqual(len(option_calls), 3)  # Three options created
            
            # Check that only option at index 1 is marked correct
            for idx, call in enumerate(option_calls):
                is_correct = call[1]['is_correct']
                if idx == 1:
                    self.assertTrue(is_correct, f"Option {idx} should be correct")
                else:
                    self.assertFalse(is_correct, f"Option {idx} should not be correct")
            
            self.assertEqual(resp.status_code, 302)

    def test_create_multiple_choice_checkbox_multiple_selection(self):
        """Test creating a multi-selection (checkbox) multiple choice question.
        
        When multiple option_correct_X checkboxes are checked, all should be marked as correct.
        allow_multiple_selections should be True.
        """
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 2
        fake_q = DummyQuestion(id=101, teacher_id=42, room_id=2, allow_multiple_selections=True)
        
        with mock.patch('dashboard.views.Room') as R, \
             mock.patch('dashboard.views.Question') as Q, \
             mock.patch('dashboard.views.QuestionOption') as QO:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            Q.objects.using.return_value.create.return_value = fake_q
            QO.objects.using.return_value.create = mock.MagicMock()

            # Create with checkboxes: options 0 and 2 are correct
            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '2',
                'qtype': 'multiple_choice',
                'title': 'Select all that apply',
                'body': 'Pick multiple correct answers',
                'option_0': 'Correct A',
                'option_1': 'Wrong',
                'option_2': 'Correct B',
                'option_correct_0': 'on',  # Checkbox: checked
                'option_correct_2': 'on',  # Checkbox: checked
                'allow_multiple_selections': 'on',  # Checked = True
            }, follow=False)
            
            # Verify question was created with allow_multiple_selections=True
            Q.objects.using.return_value.create.assert_called_once()
            call_kwargs = Q.objects.using.return_value.create.call_args[1]
            self.assertTrue(call_kwargs['allow_multiple_selections'])
            
            # Verify options 0 and 2 are marked as correct
            option_calls = QO.objects.using.return_value.create.call_args_list
            self.assertEqual(len(option_calls), 3)
            
            for idx, call in enumerate(option_calls):
                is_correct = call[1]['is_correct']
                if idx in [0, 2]:
                    self.assertTrue(is_correct, f"Option {idx} should be correct")
                else:
                    self.assertFalse(is_correct, f"Option {idx} should not be correct")
            
            self.assertEqual(resp.status_code, 302)

    def test_single_selection_mode_with_radio_button(self):
        """When allow_multiple_selections is False, use radio button for correct answer.
        
        The allow_multiple_selections flag determines the UI mode.
        When False (not checked), only option_correct_single is used.
        Checkbox flags should be ignored.
        """
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 3
        fake_q = DummyQuestion(id=102, teacher_id=42, room_id=3, allow_multiple_selections=False)
        
        with mock.patch('dashboard.views.Room') as R, \
             mock.patch('dashboard.views.Question') as Q, \
             mock.patch('dashboard.views.QuestionOption') as QO:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            Q.objects.using.return_value.create.return_value = fake_q
            QO.objects.using.return_value.create = mock.MagicMock()

            # Single-selection mode (allow_multiple_selections=False):
            # Use option_correct_single for the correct answer.
            # Ignore any checkbox flags when in single-selection mode.
            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '3',
                'qtype': 'multiple_choice',
                'title': 'Single selection via radio',
                'body': 'Test radio button mode',
                'option_0': 'A',
                'option_1': 'B (correct)',
                'option_2': 'C',
                'option_correct_single': '1',  # Radio button: option 1 is correct
                'option_correct_0': 'on',      # Checkbox flags: ignored in single-selection
                'option_correct_2': 'on',      # Checkbox flags: ignored in single-selection
                'allow_multiple_selections': '',  # False = use radio button
            }, follow=False)
            
            # Verify allow_multiple_selections is False
            call_kwargs = Q.objects.using.return_value.create.call_args[1]
            self.assertFalse(call_kwargs['allow_multiple_selections'])
            
            # Verify only option 1 is correct (from radio button)
            option_calls = QO.objects.using.return_value.create.call_args_list
            for idx, call in enumerate(option_calls):
                is_correct = call[1]['is_correct']
                if idx == 1:
                    self.assertTrue(is_correct)
                else:
                    self.assertFalse(is_correct)
            
            self.assertEqual(resp.status_code, 302)

    def test_multi_selection_with_allow_flag_true(self):
        """Test that allow_multiple_selections flag is properly set to True."""
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 4
        fake_q = DummyQuestion(id=103, teacher_id=42, room_id=4)
        
        with mock.patch('dashboard.views.Room') as R, \
             mock.patch('dashboard.views.Question') as Q, \
             mock.patch('dashboard.views.QuestionOption') as QO:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            Q.objects.using.return_value.create.return_value = fake_q
            QO.objects.using.return_value.create = mock.MagicMock()

            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '4',
                'qtype': 'multiple_choice',
                'title': 'Multi-select enabled',
                'body': 'Test',
                'option_0': 'A',
                'option_1': 'B',
                'option_correct_0': 'on',
                'allow_multiple_selections': 'on',
            }, follow=False)
            
            # Verify the flag is set to True in question creation
            Q.objects.using.return_value.create.assert_called_once()
            call_kwargs = Q.objects.using.return_value.create.call_args[1]
            self.assertTrue(call_kwargs['allow_multiple_selections'])

    def test_multi_selection_with_allow_flag_false(self):
        """Test that allow_multiple_selections flag is properly set to False."""
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 5
        fake_q = DummyQuestion(id=104, teacher_id=42, room_id=5)
        
        with mock.patch('dashboard.views.Room') as R, \
             mock.patch('dashboard.views.Question') as Q, \
             mock.patch('dashboard.views.QuestionOption') as QO:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            Q.objects.using.return_value.create.return_value = fake_q
            QO.objects.using.return_value.create = mock.MagicMock()

            # Explicitly not checking the allow_multiple_selections checkbox
            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '5',
                'qtype': 'multiple_choice',
                'title': 'Multi-select disabled',
                'body': 'Test',
                'option_0': 'A',
                'option_1': 'B',
                'option_correct_0': 'on',
                # No allow_multiple_selections key = False
            }, follow=False)
            
            # Verify the flag is set to False in question creation
            Q.objects.using.return_value.create.assert_called_once()
            call_kwargs = Q.objects.using.return_value.create.call_args[1]
            self.assertFalse(call_kwargs['allow_multiple_selections'])

    def test_multiple_correct_answers_requires_multi_selection_flag(self):
        """Test that multiple correct answers should be paired with allow_multiple_selections=True.
        
        When student gets multiple answers, the flag should be True to indicate that
        the question allows multiple correct choices.
        """
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 6
        fake_q = DummyQuestion(id=105, teacher_id=42, room_id=6, allow_multiple_selections=True)
        
        with mock.patch('dashboard.views.Room') as R, \
             mock.patch('dashboard.views.Question') as Q, \
             mock.patch('dashboard.views.QuestionOption') as QO:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            Q.objects.using.return_value.create.return_value = fake_q
            QO.objects.using.return_value.create = mock.MagicMock()

            # Create with 3 correct answers + allow_multiple_selections=True
            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '6',
                'qtype': 'multiple_choice',
                'title': 'Pick all correct',
                'body': 'Multiple correct answers',
                'option_0': 'Correct 1',
                'option_1': 'Correct 2',
                'option_2': 'Wrong',
                'option_3': 'Correct 3',
                'option_correct_0': 'on',
                'option_correct_1': 'on',
                'option_correct_3': 'on',
                'allow_multiple_selections': 'on',
            }, follow=False)
            
            # Verify question was created with allow_multiple_selections=True
            call_kwargs = Q.objects.using.return_value.create.call_args[1]
            self.assertTrue(call_kwargs['allow_multiple_selections'])
            
            # Verify exactly 3 options are marked as correct
            option_calls = QO.objects.using.return_value.create.call_args_list
            correct_count = sum(1 for call in option_calls if call[1]['is_correct'])
            self.assertEqual(correct_count, 3)

    def test_single_selection_requires_exactly_one_correct(self):
        """Test that single-selection mode enforces exactly one correct answer."""
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 7
        fake_q = DummyQuestion(id=106, teacher_id=42, room_id=7, allow_multiple_selections=False)
        
        with mock.patch('dashboard.views.Room') as R, \
             mock.patch('dashboard.views.Question') as Q, \
             mock.patch('dashboard.views.QuestionOption') as QO:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            Q.objects.using.return_value.create.return_value = fake_q
            QO.objects.using.return_value.create = mock.MagicMock()

            # Create single-selection with option_correct_single=2
            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '7',
                'qtype': 'multiple_choice',
                'title': 'Single answer required',
                'body': 'Only one correct',
                'option_0': 'Wrong 1',
                'option_1': 'Wrong 2',
                'option_2': 'Correct',
                'option_3': 'Wrong 3',
                'option_correct_single': '2',
                'allow_multiple_selections': '',  # Empty = False
            }, follow=False)
            
            # Verify exactly 1 option is marked as correct
            option_calls = QO.objects.using.return_value.create.call_args_list
            correct_options = [idx for idx, call in enumerate(option_calls) if call[1]['is_correct']]
            self.assertEqual(len(correct_options), 1)
            self.assertEqual(correct_options[0], 2)

    def test_multi_selection_mode_ignores_radio_button(self):
        """When allow_multiple_selections is True, use checkboxes for correct answers.
        
        The allow_multiple_selections flag determines the UI mode.
        When True (checked), only checkbox selections are used.
        Any option_correct_single value should be ignored.
        """
        fake_room = mock.MagicMock()
        fake_room.teacher_id = 42
        fake_room.id = 8
        fake_q = DummyQuestion(id=107, teacher_id=42, room_id=8, allow_multiple_selections=True)
        
        with mock.patch('dashboard.views.Room') as R, \
             mock.patch('dashboard.views.Question') as Q, \
             mock.patch('dashboard.views.QuestionOption') as QO:
            R.objects.using.return_value.filter.return_value.first.return_value = fake_room
            Q.objects.using.return_value.create.return_value = fake_q
            QO.objects.using.return_value.create = mock.MagicMock()

            # Multi-selection mode (allow_multiple_selections=True):
            # Use checkboxes for correct answers.
            # Ignore option_correct_single when in multi-selection mode.
            resp = self.client.post(reverse('dashboard:create_question'), {
                'selected_room_id': '8',
                'qtype': 'multiple_choice',
                'title': 'Multi-selection via checkboxes',
                'body': 'Test checkbox mode',
                'option_0': 'A (correct)',
                'option_1': 'B',
                'option_2': 'C (correct)',
                'option_correct_single': '1',  # Radio: ignored in multi-selection
                'option_correct_0': 'on',      # Checkbox: option 0 is correct
                'option_correct_2': 'on',      # Checkbox: option 2 is correct
                'allow_multiple_selections': 'on',  # True = use checkboxes
            }, follow=False)
            
            # Verify allow_multiple_selections is True
            call_kwargs = Q.objects.using.return_value.create.call_args[1]
            self.assertTrue(call_kwargs['allow_multiple_selections'])
            
            # Verify options 0 and 2 are correct (from checkboxes, radio ignored)
            option_calls = QO.objects.using.return_value.create.call_args_list
            for idx, call in enumerate(option_calls):
                is_correct = call[1]['is_correct']
                if idx in [0, 2]:
                    self.assertTrue(is_correct, f"Option {idx} should be correct")
                else:
                    self.assertFalse(is_correct, f"Option {idx} should not be correct")
