"""Unit tests validating assembly and grouping of questions and related data.

These tests exercise `assemble_questions_for_room` behaviour using
lightweight mock objects provided by `dashboard.tests.helpers.mocks`.
"""

import datetime
from django.test import SimpleTestCase

from dashboard import utils
from dashboard.tests.helpers.mocks import (
    DummyQuestion,
    DummyQuestionOption,
    DummyQuestionResponse,
    DummyResponseOption,
    DummyRoom,
    DummyStudent,
    patch_questions,
)


class AssembleQuestionsTests(SimpleTestCase):
    def test_assemble_questions_for_room_populated(self):
        now = datetime.datetime.utcnow()
        room = DummyRoom(10)
        # Use timezone-aware datetimes aligned with utils (which uses timezone.now()).
        from django.utils import timezone
        now_aw = timezone.now()
        questions = [
            DummyQuestion(id=1, room_id=room.id, manual_active=True, start_at=None, end_at=None, created_at=now_aw),  # manual active
            DummyQuestion(id=2, room_id=room.id, manual_active=False, start_at=now_aw + datetime.timedelta(hours=1), end_at=None, created_at=now_aw),  # future
            DummyQuestion(id=3, room_id=room.id, manual_active=False, start_at=now_aw - datetime.timedelta(hours=2), end_at=now_aw - datetime.timedelta(hours=1), created_at=now_aw),  # past
        ]
        options = [
            DummyQuestionOption(id=11, question_id=1, position=0),
            DummyQuestionOption(id=12, question_id=1, position=1),
            DummyQuestionOption(id=21, question_id=2, position=0),
        ]
        responses = [
            DummyQuestionResponse(id=101, question_id=1, student_id=501, option_id=11, answer_text=None, submitted_at=now_aw, score=None),
            DummyQuestionResponse(id=102, question_id=1, student_id=502, option_id=None, answer_text="Free", submitted_at=now_aw, score=1.0),
        ]
        response_options = [
            DummyResponseOption(response_id=102, option_id=12),  # multi-answer for second response
        ]
        students = [
            DummyStudent(id=501, moodle_id=9001, matrix_id='@s1:test'),
            DummyStudent(id=502, moodle_id=9002, matrix_id='@s2:test'),
        ]
        data = {
            'questions': questions,
            'options': options,
            'responses': responses,
            'response_options': response_options,
            'students': students,
        }
        with patch_questions(data):
            assembled = utils.assemble_questions_for_room(room, teacher_id=42)
        # Basic counts
        self.assertEqual(len(assembled), 3)
        qmap = {e['question'].id: e for e in assembled}
        # Question 1 manual active
        self.assertTrue(qmap[1]['is_currently_active'])
        # Future question not active yet
        self.assertFalse(qmap[2]['is_currently_active'])
        self.assertTrue(qmap[2]['before_start'])
        # Past question ended
        self.assertTrue(qmap[3]['after_end'])
        # Options grouped
        self.assertEqual(len(qmap[1]['options']), 2)
        # Responses aggregated
        self.assertEqual(len(qmap[1]['responses']), 2)
        # Multi option response includes option_ids list
        r2 = next(r for r in qmap[1]['responses'] if r['id'] == 102)
        self.assertIn(12, r2['option_ids'])

    def test_assemble_questions_ignores_empty_expected_answers(self):
        room = DummyRoom(11)
        from django.utils import timezone
        now_aw = timezone.now()
        questions = [
            DummyQuestion(
                id=4,
                room_id=room.id,
                manual_active=True,
                start_at=None,
                end_at=None,
                created_at=now_aw,
                qtype='short_answer',
                expected_answer='',
            ),
            DummyQuestion(
                id=5,
                room_id=room.id,
                manual_active=True,
                start_at=None,
                end_at=None,
                created_at=now_aw,
                qtype='numeric',
                expected_answer='   ',
            ),
        ]
        responses = [
            DummyQuestionResponse(id=201, question_id=4, student_id=601, option_id=None, answer_text='alpha', submitted_at=now_aw, score=None),
            DummyQuestionResponse(id=202, question_id=5, student_id=602, option_id=None, answer_text='42', submitted_at=now_aw, score=None),
        ]
        students = [
            DummyStudent(id=601, moodle_id=9101, matrix_id='@s3:test'),
            DummyStudent(id=602, moodle_id=9102, matrix_id='@s4:test'),
        ]
        data = {
            'questions': questions,
            'options': [],
            'responses': responses,
            'response_options': [],
            'students': students,
        }
        with patch_questions(data):
            assembled = utils.assemble_questions_for_room(room, teacher_id=42)

        qmap = {e['question'].id: e for e in assembled}
        self.assertIsNone(qmap[4]['responses'][0]['expected_text'])
        self.assertIsNone(qmap[5]['responses'][0]['expected_text'])
