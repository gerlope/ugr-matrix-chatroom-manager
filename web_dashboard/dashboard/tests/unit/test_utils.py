"""Unit tests for core utility functions in `dashboard.utils`.

This file contains tests for availability calculations, overlap
checks and other non-networking helpers.
"""

import datetime
from unittest import mock
from django.test import SimpleTestCase

from dashboard import utils
from dashboard.tests.helpers.mocks import (
    DummyAvail,
    DummyQuestion,
    DummyQuestionOption,
    patch_teacher_availability,
)

class UtilsTests(SimpleTestCase):
    def test_build_availability_display_basic(self):
        rows = [
            DummyAvail(1, 'Monday', datetime.time(8, 0), datetime.time(9, 0)),
            DummyAvail(2, 'Monday', datetime.time(10, 30), datetime.time(11, 0)),
            DummyAvail(3, 'Wednesday', datetime.time(7, 0), datetime.time(7, 30)),
        ]
        result = utils.build_availability_display(rows, timeline_start_hour=7, timeline_end_hour=21)
        self.assertIn('days_with_slots', result)
        monday_slots = [d for d in result['days_with_slots'] if d['day'] == 'Lunes'][0]['slots']
        self.assertEqual(len(monday_slots), 2)
        # Percentages within bounds
        for slot in monday_slots:
            self.assertGreaterEqual(slot['left_pct'], 0)
            self.assertLessEqual(slot['left_pct'], 100)
            self.assertGreaterEqual(slot['width_pct'], 0)
            self.assertLessEqual(slot['width_pct'], 100)

    def test_assemble_questions_for_room_none(self):
        self.assertEqual(utils.assemble_questions_for_room(None, teacher_id=1), [])

    def test_check_availability_overlap_detects(self):
        existing = [
            DummyAvail(1, 'Monday', datetime.time(8, 0), datetime.time(9, 0)),
            DummyAvail(2, 'Monday', datetime.time(10, 0), datetime.time(11, 0)),
        ]
        with patch_teacher_availability(existing):
            conflict = utils.check_availability_overlap(
                teacher_id=5,
                day='Monday',
                start_time=datetime.time(8, 30),
                end_time=datetime.time(9, 30)
            )
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.id, 1)

    def test_check_availability_overlap_none(self):
        existing = [
            DummyAvail(1, 'Monday', datetime.time(8, 0), datetime.time(9, 0)),
        ]
        with patch_teacher_availability(existing):
            conflict = utils.check_availability_overlap(
                teacher_id=5,
                day='Monday',
                start_time=datetime.time(9, 0),
                end_time=datetime.time(10, 0)
            )
        self.assertIsNone(conflict)

    def test_check_availability_overlap_cases(self):
        base = DummyAvail(1, 'Monday', datetime.time(8, 0), datetime.time(10, 0))
        cases = [
            (datetime.time(7, 30), datetime.time(8, 30), True),  # partial at start
            (datetime.time(9, 30), datetime.time(10, 30), True),  # partial at end
            (datetime.time(8, 0), datetime.time(10, 0), True),   # exact match
            (datetime.time(10, 0), datetime.time(11, 0), False), # touching end
            (datetime.time(7, 0), datetime.time(8, 0), False),   # touching start
            (datetime.time(8, 30), datetime.time(9, 30), True),  # inside existing
        ]
        for st, et, expected in cases:
            with self.subTest(start=st, end=et):
                with patch_teacher_availability([base]):
                    conflict = utils.check_availability_overlap(
                        teacher_id=99,
                        day='Monday',
                        start_time=st,
                        end_time=et,
                    )
                if expected:
                    self.assertIsNotNone(conflict)
                else:
                    self.assertIsNone(conflict)

    def test_extract_expected_answers_normalizes_and_skips_answer_option(self):
        question = DummyQuestion(expected_answer=' 42 ')
        options = [
            DummyQuestionOption(id=1, option_key='A', text='Alpha', is_correct=True),
            DummyQuestionOption(id=2, option_key='ANSWER', text='Ignored', is_correct=True),
            DummyQuestionOption(id=3, option_key='B', text='Beta', is_correct=False),
        ]
        expected_text, expected_options = utils.extract_expected_answers(options, question)
        self.assertEqual(expected_text, '42')
        self.assertEqual(len(expected_options), 1)
        self.assertEqual(expected_options[0]['option_key'], 'A')

    def test_extract_expected_answers_empty_text(self):
        question = DummyQuestion(expected_answer='   ')
        expected_text, expected_options = utils.extract_expected_answers([], question)
        self.assertIsNone(expected_text)
        self.assertEqual(expected_options, [])

    def test_extract_expected_answers_without_question(self):
        options = [
            DummyQuestionOption(id=1, option_key='A', text='Alpha', is_correct=True),
            DummyQuestionOption(id=2, option_key='B', text='Beta', is_correct=False),
        ]
        expected_text, expected_options = utils.extract_expected_answers(options, None)
        self.assertIsNone(expected_text)
        self.assertEqual(len(expected_options), 1)
        self.assertEqual(expected_options[0]['option_key'], 'A')

    def test_build_selected_options_single_and_multi(self):
        options = [
            DummyQuestionOption(id=11, option_key='A', text='Alpha', is_correct=False),
            DummyQuestionOption(id=12, option_key='B', text='Beta', is_correct=True),
        ]
        selected_single = utils.build_selected_options({'option_id': 11}, options)
        self.assertEqual(len(selected_single), 1)
        self.assertEqual(selected_single[0]['id'], 11)

        selected_multi = utils.build_selected_options({'option_ids': [12, '11']}, options)
        selected_ids = {entry['id'] for entry in selected_multi}
        self.assertEqual(selected_ids, {11, 12})

    def test_build_selected_options_ignores_invalid_ids(self):
        options = [DummyQuestionOption(id=11, option_key='A', text='Alpha', is_correct=False)]
        selected = utils.build_selected_options({'option_ids': ['x', None]}, options)
        self.assertEqual(selected, [])

    def test_calculate_score_distribution_no_graded(self):
        dist = utils._calculate_score_distribution([
            {'is_graded': False, 'score': 100},
            {'is_graded': False, 'score': None},
        ])
        self.assertEqual(dist['total'], 0)
        self.assertIsNone(dist['average'])

    def test_calculate_score_distribution_mixed_scores(self):
        dist = utils._calculate_score_distribution([
            {'is_graded': True, 'score': None},
            {'is_graded': True, 'score': 100},
            {'is_graded': True, 'score': 74},
            {'is_graded': True, 'score': 50},
            {'is_graded': True, 'score': 0},
            {'is_graded': False, 'score': 100},
        ])
        self.assertEqual(dist['bracket_100'], 1)
        self.assertEqual(dist['bracket_75_99'], 0)
        self.assertEqual(dist['bracket_50_74'], 2)
        self.assertEqual(dist['bracket_0_49'], 1)
        self.assertEqual(dist['no_score'], 1)
        self.assertEqual(dist['total'], 5)
        self.assertEqual(dist['average'], 56.0)

    def test_mark_latest_submissions_without_multiple(self):
        responses = [
            {'student_id': 1, 'response_version': 1, 'allow_multiple_submissions': False},
            {'student_id': 2, 'response_version': 1, 'allow_multiple_submissions': False},
        ]
        utils._mark_latest_submissions(responses)
        self.assertTrue(all(r.get('is_latest_submission') for r in responses))

    def test_mark_latest_submissions_with_multiple(self):
        responses = [
            {'student_id': 1, 'response_version': 1, 'allow_multiple_submissions': True},
            {'student_id': 1, 'response_version': 2, 'allow_multiple_submissions': True},
            {'student_id': 2, 'response_version': 1, 'allow_multiple_submissions': True},
        ]
        utils._mark_latest_submissions(responses)
        latest = {r['student_id']: r['response_version'] for r in responses if r.get('is_latest_submission')}
        self.assertEqual(latest, {1: 2, 2: 1})

    def test_filter_latest_submissions_mixed(self):
        responses = [
            {'student_id': 1, 'question_id': 10, 'response_version': 1, 'allow_multiple_submissions': True},
            {'student_id': 1, 'question_id': 10, 'response_version': 2, 'allow_multiple_submissions': True},
            {'student_id': 2, 'question_id': 10, 'response_version': 1, 'allow_multiple_submissions': True},
            {'student_id': 3, 'question_id': 11, 'response_version': 1, 'allow_multiple_submissions': False},
        ]
        latest = utils._filter_latest_submissions(responses, group_by='student')
        latest_by_student = {r['student_id']: r['response_version'] for r in latest}
        self.assertEqual(latest_by_student[1], 2)
        self.assertEqual(latest_by_student[2], 1)
        self.assertEqual(latest_by_student[3], 1)
