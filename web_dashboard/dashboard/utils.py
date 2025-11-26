"""Dashboard utility functions.

This module centralizes logic used by the dashboard views for:
 - Building availability timelines
 - Fetching & assembling Moodle + internal (bot_db) data for courses/rooms/questions
 - Overlap validation for teacher availability intervals
 - Preparing common schedule context

Refactored structure:
 - Availability helpers: build_availability_display, check_availability_overlap
 - Moodle data fetchers: fetch_moodle_courses, fetch_moodle_groups, fetch_enrolled_students
 - Question response enrichment: extract_expected_answers, build_selected_options,
   enrich_response_with_options, attach_student_responses
 - Student data building: build_student_entry
 - Room data assembly: assemble_questions_for_room
 - High-level aggregation: get_data_for_dashboard, process_course_data
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from django.db.models import Max, Sum
from django.utils import timezone
import datetime

from .models import (
    ExternalUser,
    Reaction,
    Room,
    Question,
    QuestionOption,
    ResponseOption,
    QuestionResponse,
    TeacherAvailability,
)
from config import MOODLE_TOKEN, MOODLE_URL

WEEK_DAYS_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

# ---------------------------------------------------------------------------
# Score distribution helpers
# ---------------------------------------------------------------------------

def _calculate_score_distribution(responses_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate score distribution with percentages and offsets for pie chart.
    Only includes graded responses (is_graded=True)."""
    dist = {'bracket_0_49': 0, 'bracket_50_74': 0, 'bracket_75_99': 0, 'bracket_100': 0, 'no_score': 0}
    
    # Filter to only graded responses
    graded_responses = [er for er in responses_list if er.get('is_graded')]
    
    for er in graded_responses:
        score = er.get('score')
        if score is None:
            dist['no_score'] += 1
        elif score == 100:
            dist['bracket_100'] += 1
        elif score >= 75:
            dist['bracket_75_99'] += 1
        elif score >= 50:
            dist['bracket_50_74'] += 1
        else:
            dist['bracket_0_49'] += 1
    
    total = sum(dist.values())
    dist['total'] = total
    
    if total > 0:
        dist['pct_0_49'] = (dist['bracket_0_49'] / total) * 100
        dist['pct_50_74'] = (dist['bracket_50_74'] / total) * 100
        dist['pct_75_99'] = (dist['bracket_75_99'] / total) * 100
        dist['pct_100'] = (dist['bracket_100'] / total) * 100
        dist['pct_no_score'] = (dist['no_score'] / total) * 100
        
        dist['offset_50_74'] = -dist['pct_0_49']
        dist['offset_75_99'] = -(dist['pct_0_49'] + dist['pct_50_74'])
        dist['offset_100'] = -(dist['pct_0_49'] + dist['pct_50_74'] + dist['pct_75_99'])
        dist['offset_no_score'] = -(dist['pct_0_49'] + dist['pct_50_74'] + dist['pct_75_99'] + dist['pct_100'])
        
        scores = [er.get('score') for er in graded_responses if er.get('score') is not None]
        dist['average'] = round(sum(scores) / len(scores), 1) if scores else None
    else:
        dist['average'] = None
    
    return dist


def _calculate_participation(answered: int, total: int) -> Dict[str, Any]:
    """Calculate participation percentages for pie chart."""
    not_answered = total - answered
    participation = {
        'answered': answered,
        'not_answered': not_answered,
        'total': total,
    }
    
    if total > 0:
        participation['pct_answered'] = (answered / total) * 100
        participation['pct_not_answered'] = (not_answered / total) * 100
        participation['offset_not_answered'] = -participation['pct_answered']
    else:
        participation['pct_answered'] = 0
        participation['pct_not_answered'] = 0
        participation['offset_not_answered'] = 0
    
    return participation


# ---------------------------------------------------------------------------
# Availability helpers
# ---------------------------------------------------------------------------


def build_availability_display(avail_rows, timeline_start_hour: int = 7, timeline_end_hour: int = 21) -> Dict[str, Any]:
    """Builds availability dict, days_with_slots and timeline hours for templates.

    Returns a dict with keys: en_to_es, timeline_hours, availability, days_with_slots,
    timeline_start_hour, timeline_end_hour, timeline_span
    """
    en_to_es = {
        'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
        'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
    }
    timeline_span = timeline_end_hour - timeline_start_hour

    # Initialize availability dict
    availability = {v: [] for v in en_to_es.values()}

    for a in avail_rows:
        day_en = (a.day_of_week or '')
        day_es = en_to_es.get(day_en, day_en)
        # defaults
        left_pct = 0.0
        width_pct = 0.0
        top_pct = 0.0
        height_pct = 0.0
        try:
            sh = a.start_time.hour + a.start_time.minute / 60.0
            eh = a.end_time.hour + a.end_time.minute / 60.0
            # clamp to timeline window
            sh_clamped = max(timeline_start_hour, min(sh, timeline_end_hour))
            eh_clamped = max(timeline_start_hour, min(eh, timeline_end_hour))
            left_pct = ((sh_clamped - timeline_start_hour) / timeline_span) * 100
            width_pct = ((max(eh_clamped, sh_clamped) - sh_clamped) / timeline_span) * 100
            # For vertical rendering we map left->top and width->height
            top_pct = left_pct
            height_pct = width_pct
            start_s = a.start_time.strftime('%H:%M') if a.start_time else ''
            end_s = a.end_time.strftime('%H:%M') if a.end_time else ''
        except Exception:
            # fallback values if time parsing fails
            start_s = str(a.start_time)
            end_s = str(a.end_time)
            left_pct = 0.0
            width_pct = 0.0
            top_pct = 0.0
            height_pct = 0.0

        availability.setdefault(day_es, []).append({
            'id': getattr(a, 'id', None),
            'start': start_s,
            'end': end_s,
            'left_pct': left_pct,
            'width_pct': width_pct,
            'top_pct': top_pct,
            'height_pct': height_pct,
        })

    week_days = WEEK_DAYS_ES
    timeline_hours = list(range(timeline_start_hour, timeline_end_hour))
    days_with_slots = []
    for d in week_days:
        days_with_slots.append({'day': d, 'slots': availability.get(d, [])})

    return {
        'en_to_es': en_to_es,
        'timeline_hours': timeline_hours,
        'availability': availability,
        'days_with_slots': days_with_slots,
        'timeline_start_hour': timeline_start_hour,
        'timeline_end_hour': timeline_end_hour,
        'timeline_span': timeline_span,
    }


def check_availability_overlap(teacher_id: int, day: str, start_time, end_time, exclude_id: Optional[int] = None):
    """Return the conflicting availability instance if the interval overlaps, else None.

    Overlap rule: (new_start < existing_end) AND (new_end > existing_start)
    ``exclude_id`` allows ignoring self for edits.
    """
    qs = ExternalUser.objects.none()  # placeholder for type; real queryset below

    q = TeacherAvailability.objects.using('bot_db').filter(teacher_id=teacher_id, day_of_week=day)
    if exclude_id is not None:
        q = q.exclude(id=exclude_id)
    for existing in q:
        try:
            if start_time < existing.end_time and end_time > existing.start_time:
                return existing
        except Exception:
            # Ignore problematic rows (corrupted times)
            continue
    return None


# ---------------------------------------------------------------------------
# Moodle / external data fetch helpers
# ---------------------------------------------------------------------------
def _moodle_endpoint() -> str:
    return f"{MOODLE_URL}/webservice/rest/server.php"


def fetch_moodle_courses(teacher: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = {
        'wstoken': MOODLE_TOKEN,
        'wsfunction': 'core_enrol_get_users_courses',
        'moodlewsrestformat': 'json',
        'userid': teacher["moodle_id"],
    }
    try:
        resp = requests.get(_moodle_endpoint(), params=params, timeout=20)
        resp.raise_for_status()
        return resp.json() or []
    except Exception as e:
        print(f"[Dashboard] Error fetching courses: {e}")
        return []


def fetch_moodle_groups(course_id: int) -> List[Dict[str, Any]]:
    params = {
        'wstoken': MOODLE_TOKEN,
        'wsfunction': 'core_group_get_course_groups',
        'moodlewsrestformat': 'json',
        'courseid': course_id,
    }
    try:
        resp = requests.get(_moodle_endpoint(), params=params, timeout=20)
        resp.raise_for_status()
        groups_data = resp.json() or []
    except Exception as e:
        print(f"[Dashboard] Error fetching groups for course {course_id}: {e}")
        return []
    return [{'id': g.get('id'), 'name': g.get('name')} for g in groups_data]


def fetch_moodle_group_members(group_id: int) -> List[int]:
    """Fetch members of a specific Moodle group."""
    params = {
        'wstoken': MOODLE_TOKEN,
        'wsfunction': 'core_group_get_group_members',
        'moodlewsrestformat': 'json',
        'groupids[0]': group_id,
    }
    try:
        resp = requests.get(_moodle_endpoint(), params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json() or []
        # API returns list of groups, each with userids array
        if data and len(data) > 0:
            return data[0].get('userids', [])
        return []
    except Exception as e:
        print(f"[Dashboard] Error fetching group members for group {group_id}: {e}")
        return []


def fetch_enrolled_students(course_id: int) -> List[Dict[str, Any]]:
    params = {
        'wstoken': MOODLE_TOKEN,
        'wsfunction': 'core_enrol_get_enrolled_users',
        'moodlewsrestformat': 'json',
        'courseid': course_id,
    }
    try:
        resp = requests.get(_moodle_endpoint(), params=params, timeout=20)
        resp.raise_for_status()
        return resp.json() or []
    except Exception as e:
        print(f"[Dashboard] Error fetching enrolled users for course {course_id}: {e}")
        return []


# ---------------------------------------------------------------------------
# Question response enrichment helpers
# ---------------------------------------------------------------------------

def extract_expected_answers(options: List[QuestionOption]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Extract expected text (for short_answer/numeric) and expected options (for multiple_choice)."""
    expected_text = None
    expected_options = []
    
    try:
        for o in options:
            # short_answer/numeric expected value stored under option_key 'ANSWER'
            if getattr(o, 'option_key', None) == 'ANSWER' and getattr(o, 'text', None):
                expected_text = o.text
        
        # for multiple choice, collect correct options but skip ANSWER pseudo-option
        for o in options:
            try:
                if getattr(o, 'is_correct', False) and getattr(o, 'option_key', None) != 'ANSWER':
                    expected_options.append({
                        'id': getattr(o, 'id', None),
                        'option_key': getattr(o, 'option_key', None),
                        'text': getattr(o, 'text', None)
                    })
            except Exception:
                continue
    except Exception:
        expected_text = None
        expected_options = []
    
    return expected_text, expected_options


def build_selected_options(response: Dict[str, Any], question_options: List[QuestionOption]) -> List[Dict[str, Any]]:
    """Build selected options list by matching response option_ids against question options."""
    selected_options = []
    
    try:
        # Ensure we have a list of option IDs (handle both option_id and option_ids)
        resp_opt_ids = response.get('option_ids') or ([] if response.get('option_id') is None else [response.get('option_id')])
        
        if resp_opt_ids:
            for o in question_options:
                opt_id = getattr(o, 'id', None)
                # Compare as integers to handle type mismatches
                if opt_id and any(int(opt_id) == int(rid) for rid in resp_opt_ids if rid is not None):
                    selected_options.append({
                        'id': opt_id,
                        'option_key': getattr(o, 'option_key', None),
                        'text': getattr(o, 'text', None),
                        'is_correct': getattr(o, 'is_correct', False),
                    })
    except Exception as e:
        print(f"[WARN] Error building selected_options for response {response.get('id')}: {e}")
        selected_options = []
    
    return selected_options


def build_student_entry(student_db: ExternalUser, enrolled_data: List[Dict[str, Any]], 
                        reactions: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a standardized student entry dict from DB and Moodle data."""
    moodle_user = next((s for s in enrolled_data if s['id'] == student_db.moodle_id), None)
    
    return {
        'id': student_db.id,
        'moodle_id': student_db.moodle_id,
        'matrix_id': student_db.matrix_id,
        'full_name': moodle_user.get('fullname', None) if moodle_user else 'Desconocido',
        'reactions': [r for r in reactions if r['student_id'] == student_db.id],
        'groups': moodle_user.get('groups', None) if moodle_user else []
    }


def enrich_response_with_options(response: Dict[str, Any], question_options: List[QuestionOption], 
                                   expected_text: Optional[str], expected_options: List[Dict[str, Any]], 
                                   question_type: Optional[str] = None) -> Dict[str, Any]:
    """Enrich a response dict with expected answers and selected options."""
    return {
        **response,
        'expected_text': expected_text,
        'expected_options': expected_options,
        'selected_options': build_selected_options(response, question_options),
        'question_type': question_type,
    }


def attach_student_responses(students: List[Dict[str, Any]], questions: List[Dict[str, Any]]) -> None:
    """Attach aggregated responses to each student and enrich per-question responses.
    
    Modifies students and questions lists in-place.
    """
    student_responses_map = {}
    student_names_map = {s.get('id'): s.get('full_name') for s in students}
    student_answered_questions = {}
    
    # Build a map of room_id to room moodle_group for filtering
    room_group_map = {}
    for qentry in questions:
        qobj = qentry.get('question')
        if qobj and hasattr(qobj, 'room_id'):
            try:
                from .models import Room
                room = Room.objects.using('bot_db').get(id=qobj.room_id)
                room_group_map[qobj.room_id] = getattr(room, 'moodle_group', None)
            except Exception:
                room_group_map[qobj.room_id] = None
    
    # Build enriched responses map
    for qentry in questions:
        qobj = qentry.get('question')
        qtitle = getattr(qobj, 'title', None) or f"Pregunta {getattr(qobj, 'id', '')}"
        expected_text, expected_options = extract_expected_answers(qentry.get('options', []))

        for r in qentry.get('responses', []):
            student_id = r.get('student_id')
            qid = getattr(qobj, 'id', None)
            
            if student_id and qid:
                student_answered_questions.setdefault(student_id, set()).add(qid)
            
            enriched_resp = {
                **r,
                'question_title': qtitle,
                'question_type': getattr(qobj, 'qtype', None),
                'expected_text': expected_text,
                'expected_options': expected_options,
                'selected_options': build_selected_options(r, qentry.get('options', [])),
                'student_full_name': student_names_map.get(student_id),
            }
            student_responses_map.setdefault(student_id, []).append(enriched_resp)

    enriched_by_id = {
        enr.get('id'): enr
        for resp_list in student_responses_map.values()
        for enr in resp_list
    }

    # Attach sorted responses to each student
    for s in students:
        s_db_id = s.get('id')
        rlist = student_responses_map.get(s_db_id, [])
        try:
            rlist.sort(key=lambda x: x.get('submitted_at') or datetime.datetime.min, reverse=True)
        except Exception:
            pass
        s['responses'] = rlist
        
        # Calculate score distributions
        s['score_distribution'] = _calculate_score_distribution(rlist)
        manual_graded = [er for er in rlist if er.get('grader_id') is not None]
        s['score_distribution_manual'] = _calculate_score_distribution(manual_graded)
        
        # Calculate participation (excluding questions from group-restricted rooms student is not part of)
        student_groups = s.get('groups', []) or []
        student_group_ids = {g.get('id') for g in student_groups if isinstance(g, dict) and 'id' in g}
        
        # Filter questions to only count those accessible to this student
        accessible_questions = []
        for qentry in questions:
            qobj = qentry.get('question')
            if qobj and hasattr(qobj, 'room_id'):
                room_moodle_group = room_group_map.get(qobj.room_id)
                if room_moodle_group:
                    # Room is restricted to a moodle group
                    # Check if student is in that group (by ID or name)
                    try:
                        group_id = int(room_moodle_group)
                        if group_id in student_group_ids:
                            accessible_questions.append(qentry)
                    except (ValueError, TypeError):
                        # moodle_group is a name, check by name
                        if any(g.get('name') == room_moodle_group for g in student_groups):
                            accessible_questions.append(qentry)
                else:
                    # No group restriction, question is accessible
                    accessible_questions.append(qentry)
        
        total_questions = len(accessible_questions)
        answered_questions = len(student_answered_questions.get(s_db_id, set()))
        s['participation'] = _calculate_participation(answered_questions, total_questions)
    
    # Enrich per-question responses
    for entry in questions:
        for r in entry.get('responses', []):
            enriched = enriched_by_id.get(r.get('id'))
            if enriched:
                r.update({k: v for k, v in enriched.items() if k not in ['id', 'question_type']})
                if 'question_type' not in r:
                    r['question_type'] = enriched.get('question_type')


def assemble_questions_for_room(selected_room, teacher_id: int) -> List[Dict[str, Any]]:
    """Collect questions/options/responses for a given room.

    Keeps logic mostly identical to prior implementation while improving readability.
    """
    if selected_room is None:
        return []
    
    # Fetch Moodle group student IDs if room is bound to a group
    moodle_group_student_ids = None
    if selected_room.moodle_group:
        try:
            # Get course ID from room's moodle_course_id
            if hasattr(selected_room, 'moodle_course_id') and selected_room.moodle_course_id:
                groups = fetch_moodle_groups(selected_room.moodle_course_id)
                group_obj = next((g for g in groups if g['name'] == selected_room.moodle_group), None)
                if not group_obj:
                    try:
                        group_id = int(selected_room.moodle_group)
                        group_obj = next((g for g in groups if g['id'] == group_id), None)
                    except (ValueError, TypeError):
                        pass
                
                if group_obj:
                    group_member_ids = fetch_moodle_group_members(group_obj['id'])
                    enrolled_data = fetch_enrolled_students(selected_room.moodle_course_id)
                    group_enrolled_data = [s for s in enrolled_data if s['id'] in group_member_ids and s.get('roles') and any(r['shortname'] == 'student' for r in s['roles'])]
                    student_moodle_ids = [s['id'] for s in group_enrolled_data]
                    student_db_data = ExternalUser.objects.using('bot_db').filter(moodle_id__in=student_moodle_ids)
                    moodle_group_student_ids = [s.id for s in student_db_data]
        except Exception as e:
            print(f"[WARN] Could not fetch group members for room {selected_room.shortcode}: {e}")
    
    try:
        qs = list(Question.objects.using('bot_db').filter(room_id=selected_room.id).order_by('-created_at'))
        qids = [q.id for q in qs]
        question_options: Dict[int, List[QuestionOption]] = {}
        if qids:
            opts = QuestionOption.objects.using('bot_db').filter(question_id__in=qids).order_by('question_id', 'position')
            for opt in opts:
                question_options.setdefault(opt.question_id, []).append(opt)
        now = timezone.now()
        selected_questions: List[Dict[str, Any]] = []
        for q in qs:
            if q.start_at is None and q.end_at is None:
                within_window = False
            else:
                try:
                    within_window = ((q.start_at is None or now >= q.start_at) and (q.end_at is None or now <= q.end_at))
                except Exception:
                    within_window = True

            before_start = False
            after_end = False
            try:
                if q.start_at is not None and now < q.start_at:
                    before_start = True
                if q.end_at is not None and now > q.end_at:
                    after_end = True
            except Exception:
                pass

            is_currently_active = bool(q.manual_active) or within_window
            selected_questions.append({
                'question': q,
                'options': question_options.get(q.id, []),
                'is_currently_active': is_currently_active,
                'within_window': within_window,
                'before_start': before_start,
                'after_end': after_end,
                'responses': [],
                'score_distribution': {'bracket_0_49': 0, 'bracket_50_74': 0, 'bracket_75_99': 0, 'bracket_100': 0, 'no_score': 0, 'total': 0},
                'score_distribution_manual': {'bracket_0_49': 0, 'bracket_50_74': 0, 'bracket_75_99': 0, 'bracket_100': 0, 'no_score': 0, 'total': 0},
            })

        # Attach responses
        if qids:
            try:
                resp_qs = list(QuestionResponse.objects.using('bot_db').filter(question_id__in=qids).order_by('-submitted_at'))
                resp_ids = [r.id for r in resp_qs]
                resp_opts_map: Dict[int, List[int]] = {}
                if resp_ids:
                    resp_opts_qs = ResponseOption.objects.using('bot_db').filter(response_id__in=resp_ids).values('response_id', 'option_id')
                    for ro in resp_opts_qs:
                        resp_opts_map.setdefault(ro['response_id'], []).append(ro['option_id'])

                student_ids = list({r.student_id for r in resp_qs})
                students_map: Dict[int, ExternalUser] = {}
                if student_ids:
                    users = ExternalUser.objects.using('bot_db').filter(id__in=student_ids)
                    for u in users:
                        students_map[u.id] = u

                # Collect grader ids to map to ExternalUser objects (teachers or graders)
                grader_ids = list({getattr(r, 'grader_id') for r in resp_qs if getattr(r, 'grader_id', None)})
                graders_map: Dict[int, ExternalUser] = {}
                if grader_ids:
                    gusers = ExternalUser.objects.using('bot_db').filter(id__in=grader_ids)
                    for gu in gusers:
                        graders_map[gu.id] = gu

                # Build a map of question_id to question object for getting question_type
                questions_map = {q.id: q for q in qs}

                q_responses: Dict[int, List[Dict[str, Any]]] = {}
                for r in resp_qs:
                    # Get the question object to access its type
                    question_obj = questions_map.get(r.question_id)
                    qtype = getattr(question_obj, 'qtype', None) if question_obj else None
                    
                    q_responses.setdefault(r.question_id, []).append({
                        'id': r.id,
                        'student_id': r.student_id,
                        'student': students_map.get(r.student_id),
                        'option_id': r.option_id,
                        'option_key': getattr(qo, 'option_key', None) if (qo := next((o for o in question_options.get(r.question_id, []) if o.id == r.option_id), None)) else None,
                        'option_ids': resp_opts_map.get(r.id, []),
                        'option_keys': [getattr(qo, 'option_key', None) for qo in QuestionOption.objects.using('bot_db').filter(id__in=resp_opts_map.get(r.id, []))],
                        'answer_text': r.answer_text,
                        'submitted_at': r.submitted_at,
                        'score': getattr(r, 'score', None),
                        'is_graded': getattr(r, 'is_graded', False),
                        'grader_id': getattr(r, 'grader_id', None),
                        'grader': graders_map.get(getattr(r, 'grader_id', None)),
                        'room_id': getattr(selected_room, 'id', None),
                        'room_shortcode': getattr(selected_room, 'shortcode', None),
                        'feedback': getattr(r, 'feedback', None),
                        'question_type': qtype,
                    })

                for entry in selected_questions:
                    qobj = entry['question']
                    # Ensure responses for each question are ordered by submitted_at (most recent first)
                    resp_list = q_responses.get(qobj.id, []) or []
                    try:
                        resp_list.sort(key=lambda x: x.get('submitted_at') or datetime.datetime.min, reverse=True)
                    except Exception:
                        pass
                    
                    # Enrich responses
                    expected_text, expected_options = extract_expected_answers(entry.get('options', []))
                    qtype = getattr(qobj, 'qtype', None)
                    
                    enriched_resp_list = [
                        enrich_response_with_options(r, entry.get('options', []), expected_text, expected_options, qtype)
                        for r in resp_list
                    ]
                    entry['responses'] = enriched_resp_list
                    
                    # Calculate score distributions
                    entry['score_distribution'] = _calculate_score_distribution(enriched_resp_list)
                    manual_graded = [er for er in enriched_resp_list if er.get('grader_id') is not None]
                    entry['score_distribution_manual'] = _calculate_score_distribution(manual_graded)
                    
                    # Calculate participation distribution (only for rooms bound to Moodle groups)
                    if moodle_group_student_ids is not None:
                        students_who_answered = len(set(er.get('student_id') for er in enriched_resp_list if er.get('student_id')))
                        entry['participation_distribution'] = _calculate_participation(students_who_answered, len(moodle_group_student_ids))
                    else:
                        entry['participation_distribution'] = None
                    
                    # Calculate submission count distribution (only for questions with allow_multiple_submissions)
                    if getattr(qobj, 'allow_multiple_submissions', False):
                        student_submission_counts = {}
                        for er in enriched_resp_list:
                            sid = er.get('student_id')
                            if sid:
                                student_submission_counts[sid] = student_submission_counts.get(sid, 0) + 1
                        
                        submission_dist = {'bracket_1': 0, 'bracket_2': 0, 'bracket_3': 0, 'bracket_4': 0, 'bracket_5_plus': 0}
                        for count in student_submission_counts.values():
                            bracket_key = f'bracket_{count}' if count <= 4 else 'bracket_5_plus'
                            submission_dist[bracket_key] += 1
                        
                        total_students = sum(submission_dist.values())
                        submission_dist['total'] = total_students
                        
                        if total_students > 0:
                            for i in range(1, 5):
                                submission_dist[f'pct_{i}'] = (submission_dist[f'bracket_{i}'] / total_students) * 100
                            submission_dist['pct_5_plus'] = (submission_dist['bracket_5_plus'] / total_students) * 100
                            
                            submission_dist['offset_2'] = -submission_dist['pct_1']
                            submission_dist['offset_3'] = -(submission_dist['pct_1'] + submission_dist['pct_2'])
                            submission_dist['offset_4'] = -(submission_dist['pct_1'] + submission_dist['pct_2'] + submission_dist['pct_3'])
                            submission_dist['offset_5_plus'] = -(submission_dist['pct_1'] + submission_dist['pct_2'] + submission_dist['pct_3'] + submission_dist['pct_4'])
                        
                        entry['submission_distribution'] = submission_dist
                    else:
                        entry['submission_distribution'] = None
            except Exception as e:
                print(f"[WARN] Could not fetch question responses: {e}")
        return selected_questions
    except Exception as e:
        print(f"[WARN] Could not fetch questions for room {getattr(selected_room, 'shortcode', 'UNKNOWN')}: {e}")
        return []


# ---------------------------------------------------------------------------
# Original high-level dashboard data assembly (still exported)
# ---------------------------------------------------------------------------

def get_data_for_dashboard(teacher: Dict[str, Any], selected_room_id: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate courses + room/question/student data for dashboard rendering.

    Returns keys: courses, selected_room, selected_course, selected_students, selected_questions.
    Maintains original semantics for consumers.
    """
    selected_room = None
    selected_course = None
    selected_students = None
    selected_questions = None

    courses_data = fetch_moodle_courses(teacher)
    teacher_rooms = Room.objects.using('bot_db').filter(teacher_id=teacher['id'], active=True)
    general_rooms = Room.objects.using('bot_db').filter(teacher_id=None)

    course_list: List[Dict[str, Any]] = []
    thread_results: List[Optional[Dict[str, Any]]] = [None] * len(courses_data)

    # Run tasks concurrently for per-course assembly
    with ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(
                process_course_data,
                course,
                general_rooms,
                teacher_rooms,
                teacher,
                selected_room_id,
                thread_results,
                i,
            )
            for i, course in enumerate(courses_data)
        ]
        for f in futures:
            f.result()  # propagate exceptions early

    for data in thread_results:
        if not data:
            continue
        if data['selected_course'] is not None:
            selected_course = data['selected_course']
            selected_room = data['selected_room']
            selected_students = data['selected_students']
            selected_questions = data['selected_questions']
        course_list.append({
            'id': data.get('id'),
            'shortname': data.get('shortname'),
            'fullname': data.get('fullname'),
            'displayname': data.get('displayname'),
            'general_room': data['general_room'],
            'teachers_room': data['teachers_room'],
            'rooms': data['rooms'],
            'groups': data['groups'],
            'is_open': data['is_open'],
        })

    return {
        'courses': course_list,
        'selected_room': selected_room,
        'selected_course': selected_course,
        'selected_students': selected_students,
        'selected_questions': selected_questions,
    }


def process_course_data(course, general_rooms, teacher_rooms, teacher, selected_room_id, thread_results, index):
    selected_room = None
    selected_course = None
    selected_reactions = None
    selected_students = None
    selected_questions = None
    is_open = "false"
    course_id = course.get('id')
    general_room = next((room for room in general_rooms if room.shortcode == course.get('shortname')), None)
    teachers_room = next((room for room in general_rooms if room.shortcode == course.get('shortname')+"_teachers"), None)
    course_rooms = [room for room in teacher_rooms if room.moodle_course_id == course_id]
    all_rooms = course_rooms + ([general_room] if general_room else []) + ([teachers_room] if teachers_room else [])
    groups = []

    groups = fetch_moodle_groups(course_id)
    
    if selected_room_id and selected_room_id in [str(r.id) for r in all_rooms]:
        is_open = "true"
        selected_room = next((r for r in all_rooms if str(r.id) == selected_room_id), None)
        selected_course = {
            'id': course_id,
            'shortname': course.get('shortname'),
            'fullname': course.get('fullname'),
            'displayname': course.get('displayname'),
            'general_room': general_room,
            'teachers_room': teachers_room,
            'rooms': course_rooms,
            'groups': groups,
            'is_open': is_open,
        }

        enrolled_data = fetch_enrolled_students(course_id)

        if selected_room.teacher_id is None and selected_room.shortcode == course.get('shortname'):
            # General room: aggregate reactions and students from all course rooms
            selected_reactions = (Reaction.objects.using('bot_db').filter(teacher_id=teacher['id'],
                                                                              room_id__in=[room.id for room in course_rooms + ([general_room] if general_room else [])])
                                                                      .values('student_id', 'emoji')
                                                                      .annotate(total_count=Sum('count'), 
                                                                                latest_update=Max('last_updated')))                

            selected_students = []
            student_moodle_ids = [s['id'] for s in enrolled_data if s.get('roles') and any(r['shortname'] == 'student' for r in s['roles'])]
            student_db_data = ExternalUser.objects.using('bot_db').filter(moodle_id__in=student_moodle_ids)
            
            for student in student_db_data:
                selected_students.append(build_student_entry(student, enrolled_data, selected_reactions))
                
        elif selected_room.teacher_id == teacher['id']:
            # Specific teacher room: get reactions and students for this room only
            selected_reactions = (Reaction.objects.using('bot_db').filter(teacher_id=teacher['id'], 
                                                                              room_id=selected_room_id)
                                                                      .values('student_id', 'emoji')
                                                                      .annotate(total_count=Sum('count'), 
                                                                                latest_update=Max('last_updated')))
            
            selected_students = []
            
            # Check if room is bound to a Moodle group
            if selected_room.moodle_group:
                # Room bound to Moodle group: fetch users from that group only
                try:
                    # Try to find group by name first, then by ID
                    group_obj = next((g for g in groups if g['name'] == selected_room.moodle_group), None)
                    if not group_obj:
                        # Try matching by ID if moodle_group is numeric
                        try:
                            group_id = int(selected_room.moodle_group)
                            group_obj = next((g for g in groups if g['id'] == group_id), None)
                        except (ValueError, TypeError):
                            pass
                    
                    if group_obj:
                        group_member_ids = fetch_moodle_group_members(group_obj['id'])
                        # Filter enrolled students to only those in the group
                        group_enrolled_data = [s for s in enrolled_data if s['id'] in group_member_ids and s.get('roles') and any(r['shortname'] == 'student' for r in s['roles'])]
                        student_moodle_ids = [s['id'] for s in group_enrolled_data]
                        student_db_data = ExternalUser.objects.using('bot_db').filter(moodle_id__in=student_moodle_ids)
                        
                        for student in student_db_data:
                            selected_students.append(build_student_entry(student, enrolled_data, selected_reactions))
                except Exception as e:
                    print(f"[Dashboard] Error loading group members for room {selected_room_id}: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                # Room not bound to group: use Matrix API (placeholder)
                participants_matrix_ids = []  # GET FROM MATRIX API
                student_db_data = ExternalUser.objects.using('bot_db').filter(matrix_id__in=participants_matrix_ids)

                for student in student_db_data:
                    selected_students.append(build_student_entry(student, enrolled_data, selected_reactions))
                
        # Fetch all questions for this selected room (including inactive / manual flags)
        # If the selected room is the course's general room, include questions from
        # all course rooms (course_rooms) plus the general room so that the
        # dashboard shows student data across the whole course.
        selected_questions = []
        try:
            if selected_room and selected_room.teacher_id is None and selected_room.shortcode == course.get('shortname'):
                # General room: aggregate questions from all course rooms
                rooms_to_assemble = list(course_rooms)
                if general_room:
                    rooms_to_assemble.append(general_room)
                for rm in rooms_to_assemble:
                    try:
                        selected_questions.extend(assemble_questions_for_room(rm, teacher['id']) or [])
                    except Exception:
                        continue  # ignore per-room failures and continue
            else:
                # Specific room: get questions for this room only
                selected_questions = assemble_questions_for_room(selected_room, teacher['id'])
        except Exception:
            selected_questions = []

        # Attach student responses if we have both students and questions
        if selected_students is not None and selected_questions:
            try:
                attach_student_responses(selected_students, selected_questions)
            except Exception as e:
                print(f"[ERROR] Failed to attach student responses: {e}")
                import traceback
                traceback.print_exc()
                pass  # best-effort; do not break dashboard assembly on errors
    
    thread_results[index] = {
        'id': course_id,
        'shortname': course.get('shortname'),
        'fullname': course.get('fullname'),
        'displayname': course.get('displayname'),
        'general_room': general_room,
        'teachers_room': teachers_room,
        'rooms': course_rooms,
        'groups': groups,
        'is_open': is_open,
        'selected_room': selected_room,
        'selected_course': selected_course,
        'selected_reactions': selected_reactions,
        'selected_students': selected_students,
        'selected_questions': selected_questions,
    }