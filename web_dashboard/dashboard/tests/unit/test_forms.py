import datetime
from django.test import SimpleTestCase

from dashboard.forms import (
    CreateAvailabilityForm,
    CreateQuestionForm,
    CreateRoomForm,
    EditAvailabilityForm,
    ExternalLoginForm,
    GradeResponseForm,
)


class ExternalLoginFormTests(SimpleTestCase):
    def test_valid_username(self):
        form = ExternalLoginForm({'username': 'teacher'})
        self.assertTrue(form.is_valid())

    def test_missing_username(self):
        form = ExternalLoginForm({})
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)


class CreateRoomFormTests(SimpleTestCase):
    def test_valid_required_fields(self):
        form = CreateRoomForm({'course_id': '10', 'shortcode': 'ABC'})
        self.assertTrue(form.is_valid())

    def test_missing_required_fields(self):
        form = CreateRoomForm({})
        self.assertFalse(form.is_valid())
        self.assertIn('course_id', form.errors)
        self.assertIn('shortcode', form.errors)

    def test_invalid_course_id(self):
        form = CreateRoomForm({'course_id': 'bad', 'shortcode': 'ABC'})
        self.assertFalse(form.is_valid())
        self.assertIn('course_id', form.errors)


class CreateQuestionFormTests(SimpleTestCase):
    def _base_data(self):
        return {
            'title': 'Sample title',
            'body': 'Sample body',
            'qtype': 'short_answer',
        }
    
    def test_missing_title_or_body(self):
        form = CreateQuestionForm(self._base_data())
        form.data['title'] = ''
        self.assertFalse(form.is_valid())
        self.assertIn('title', form.errors)

        form2 = CreateQuestionForm(self._base_data())
        form2.data['body'] = ''
        self.assertFalse(form2.is_valid())
        self.assertIn('body', form2.errors)

    def test_invalid_date_range_end_before_start(self):
        data = self._base_data()
        data.update({
            'start_at': '2026-05-11T12:00',
            'end_at': '2026-05-11T11:00',
        })
        form = CreateQuestionForm(data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_invalid_date_range_end_equals_start(self):
        data = self._base_data()
        data.update({
            'start_at': '2026-05-11T12:00',
            'end_at': '2026-05-11T12:00',
        })
        form = CreateQuestionForm(data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_valid_date_range_start_only(self):
        data = self._base_data()
        data['start_at'] = '2026-05-11T12:00'
        form = CreateQuestionForm(data)
        self.assertTrue(form.is_valid())

    def test_valid_date_range_end_only(self):
        data = self._base_data()
        data['end_at'] = '2026-05-11T12:00'
        form = CreateQuestionForm(data)
        self.assertTrue(form.is_valid())

class CreateAvailabilityFormTests(SimpleTestCase):
    def _base_data(self):
        return {
            'day_of_week': 'Monday',
            'start_time': '08:00',
            'end_time': '09:00',
        }

    def test_valid_range(self):
        form = CreateAvailabilityForm(self._base_data())
        self.assertTrue(form.is_valid())

    def test_end_before_start(self):
        data = self._base_data()
        data.update({'start_time': '10:00', 'end_time': '09:00'})
        form = CreateAvailabilityForm(data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_start_before_earliest(self):
        data = self._base_data()
        data.update({'start_time': '06:00', 'end_time': '08:00'})
        form = CreateAvailabilityForm(data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_end_after_latest(self):
        data = self._base_data()
        data.update({'start_time': '20:00', 'end_time': '22:00'})
        form = CreateAvailabilityForm(data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())


class EditAvailabilityFormTests(SimpleTestCase):
    def test_valid_range(self):
        form = EditAvailabilityForm({'start_time': '08:00', 'end_time': '09:00'})
        self.assertTrue(form.is_valid())

    def test_invalid_range(self):
        form = EditAvailabilityForm({'start_time': '09:00', 'end_time': '09:00'})
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_bounds(self):
        form = EditAvailabilityForm({'start_time': '06:30', 'end_time': '08:00'})
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

        form2 = EditAvailabilityForm({'start_time': '20:00', 'end_time': '22:00'})
        self.assertFalse(form2.is_valid())
        self.assertTrue(form2.non_field_errors())


class GradeResponseFormTests(SimpleTestCase):
    def test_valid_empty_score(self):
        form = GradeResponseForm({'feedback': 'Ok'})
        self.assertTrue(form.is_valid())

    def test_valid_boundary_scores(self):
        form = GradeResponseForm({'score': '0'})
        self.assertTrue(form.is_valid())

        form2 = GradeResponseForm({'score': '100'})
        self.assertTrue(form2.is_valid())

    def test_invalid_negative_score(self):
        form = GradeResponseForm({'score': '-1'})
        self.assertFalse(form.is_valid())
        self.assertIn('score', form.errors)

    def test_invalid_over_max_score(self):
        form = GradeResponseForm({'score': '101'})
        self.assertFalse(form.is_valid())
        self.assertIn('score', form.errors)

    def test_invalid_decimal_places(self):
        form = GradeResponseForm({'score': '10.999'})
        self.assertFalse(form.is_valid())
        self.assertIn('score', form.errors)
