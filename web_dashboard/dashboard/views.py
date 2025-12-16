from django.db import IntegrityError
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib.auth import login
from django.contrib.auth.models import User
import json
from django.core.serializers.json import DjangoJSONEncoder
import logging

from .utils import (
    get_data_for_dashboard,
    build_availability_display,
    check_availability_overlap,
    WEEK_DAYS_ES,
)
from .models import Room, ExternalUser, TeacherAvailability
from .forms import ExternalLoginForm, CreateRoomForm, CreateQuestionForm, GradeResponseForm
from .models import Question, QuestionOption, QuestionResponse
from django.utils import timezone
from config import SERVER_NAME
from .matrix_client import (
    create_room as mc_create_room,
    invite_all_members,
    USERNAME,
    join_user_admin,
    set_user_power_level,
    ensure_room_name_prefixed,
    silence_room_members,
    cancel_pending_invites,
    academic_closed_prefix,
    append_subgroup_link_to_topic,
    remove_subgroup_link_from_topic,
)
from asgiref.sync import async_to_sync
from .models import QuestionResponse
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper to serialize Django models to JSON
# ---------------------------------------------------------------------------
def serialize_for_json(obj):
    """Recursively convert Django models and other objects to JSON-serializable format."""
    from datetime import datetime, date, time
    from decimal import Decimal
    
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif hasattr(obj, '__dict__') and hasattr(obj, '_meta'):
        # Django model instance
        data = {}
        for field in obj._meta.fields:
            value = getattr(obj, field.name)
            data[field.name] = serialize_for_json(value)
        return data
    elif isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [serialize_for_json(item) for item in obj]
    else:
        return obj

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _get_teacher(request):
    """Return teacher dict stored in session or None."""
    return request.session.get('teacher')

def _render_schedule(request, teacher, extra_context=None):
    """Render schedule page with common context (courses + availability)."""
    data = get_data_for_dashboard(teacher, None)
    avail_rows = TeacherAvailability.objects.using('bot_db').filter(teacher_id=teacher['id']).order_by('day_of_week', 'start_time')
    avail_display = build_availability_display(avail_rows, timeline_start_hour=7, timeline_end_hour=21)
    ctx = {
        'teacher': teacher,
        'courses': data['courses'],
        'selected_room': data['selected_room'],
        'selected_course': data['selected_course'],
        'selected_page': 'schedule',
        'week_days': WEEK_DAYS_ES,
        'timeline_hours': avail_display['timeline_hours'],
        'days_with_slots': avail_display['days_with_slots'],
    }
    if extra_context:
        ctx.update(extra_context)
    return render(request, 'dashboard/schedule.html', ctx)

@login_required(login_url='dashboard:login')
def dashboard(request, room_id=None):
    teacher = _get_teacher(request)
    if not teacher:
        return redirect('dashboard:login')
    # Accept room_id from URL path or query parameter (for backwards compatibility)
    selected_room_id = str(room_id) if room_id else request.GET.get('room_id')
    data = get_data_for_dashboard(teacher, selected_room_id)
    questions_list = data.get('selected_questions', []) or []
    students = data['selected_students']
    
    # Serialize data for JSON download
    students_serialized = serialize_for_json(students)
    questions_serialized = serialize_for_json(questions_list)
    
    return render(request, 'dashboard/dashboard.html', {
        'teacher': teacher,
        'courses': data['courses'],
        'selected_room': data['selected_room'],
        'selected_course': data['selected_course'],
        'students': students,
        'students_json': json.dumps(students_serialized),
        'questions_list': questions_list,
        'questions_json': json.dumps(questions_serialized),
        'selected_page': 'dashboard',
    })


@login_required(login_url='dashboard:login')
def tutoring_schedule(request):
    teacher = _get_teacher(request)
    if not teacher:
        return redirect('dashboard:login')
    return _render_schedule(request, teacher)


@require_POST
@login_required(login_url='dashboard:login')
def create_availability(request):
    teacher = _get_teacher(request)
    if not teacher:
        return redirect('dashboard:login')
    from .forms import CreateAvailabilityForm
    form = CreateAvailabilityForm(request.POST)
    if not form.is_valid():
        return _render_schedule(request, teacher, {
            'create_availability_form': form,
            'show_create_availability_modal': 'true',
        })
    day = form.cleaned_data['day_of_week']
    st = form.cleaned_data['start_time']
    et = form.cleaned_data['end_time']
    conflict = check_availability_overlap(teacher['id'], day, st, et)
    if conflict:
        form.add_error(None, 'El intervalo se solapa con otro existente (%s - %s).' % (conflict.start_time.strftime('%H:%M'), conflict.end_time.strftime('%H:%M')))
        return _render_schedule(request, teacher, {
            'create_availability_form': form,
            'show_create_availability_modal': 'true',
        })
    try:
        TeacherAvailability.objects.using('bot_db').create(
            teacher_id=teacher['id'],
            day_of_week=day,
            start_time=st,
            end_time=et,
        )
        messages.success(request, 'Intervalo creado correctamente.')
    except Exception as e:
        logger.exception("Failed to create availability for teacher_id=%s", teacher.get('id'))
        messages.error(request, f'Error al crear el intervalo: {e}')
    return redirect('dashboard:tutoring_schedule')



def external_login(request):
    if request.method == "POST":
        form = ExternalLoginForm(request.POST)
        if form.is_valid():
            username = "@" + form.cleaned_data['username'] + ":" + SERVER_NAME

            try:
                teacher = ExternalUser.objects.using('bot_db').filter(matrix_id=username).first()
                if teacher:
                    if not teacher.is_teacher:
                        form.add_error(None, "Acceso denegado: no es profesor")
                        return render(request, "dashboard/login.html", {"form": form})
                    
                    # Mapear a usuario Django
                    user, created = User.objects.get_or_create(
                        username=username,
                        defaults={
                            'first_name': '',  # si no hay nombre en esta tabla
                            'last_name': '',
                            'email': '',
                            'password': '!'  # no hay password Django
                        }
                    )
                    
                    # Guardar datos en sesión
                    request.session['teacher'] = teacher.__dict__()
                    
                    # Loguear en Django
                    login(request, user)
                    
                    return redirect('dashboard:dashboard')
                else:
                    form.add_error(None, "Usuario no encontrado")
            except Exception as e:
                logger.exception("External login lookup failed for username=%s", username)
                form.add_error(None, f"Error al conectar con la base externa: {e}")
    else:
        form = ExternalLoginForm()

    return render(request, "dashboard/login.html", {"form": form})


@require_POST
@login_required(login_url='dashboard:login')
def delete_availability(request):
    """Delete a teacher availability slot (POST: avail_id)."""
    teacher = _get_teacher(request)
    if not teacher:
        return redirect('dashboard:login')
    try:
        avail_id = int(request.POST.get('avail_id'))
    except Exception:
        messages.error(request, 'ID de disponibilidad inválido.')
        return redirect('dashboard:tutoring_schedule')
    a = TeacherAvailability.objects.using('bot_db').filter(id=avail_id).first()
    if not a:
        messages.error(request, 'Disponibilidad no encontrada.')
        return redirect('dashboard:tutoring_schedule')
    if a.teacher_id != teacher['id']:
        messages.error(request, 'No tienes permiso para eliminar esta disponibilidad.')
        return redirect('dashboard:tutoring_schedule')
    try:
        a.delete(using='bot_db')
        messages.success(request, 'Intervalo eliminado correctamente.')
    except Exception as e:
        logger.exception("Failed to delete availability id=%s for teacher_id=%s", avail_id, teacher.get('id'))
        messages.error(request, f'Error al eliminar la disponibilidad: {e}')
    return redirect('dashboard:tutoring_schedule')


@require_POST
@login_required(login_url='dashboard:login')
def edit_availability(request):
    """Edit an existing availability slot (POST: avail_id, start_time, end_time)."""
    teacher = _get_teacher(request)
    if not teacher:
        return redirect('dashboard:login')
    from .forms import EditAvailabilityForm
    form = EditAvailabilityForm(request.POST)
    try:
        avail_id = int(request.POST.get('avail_id'))
    except Exception:
        messages.error(request, 'ID de disponibilidad inválido.')
        return redirect('dashboard:tutoring_schedule')
    a = TeacherAvailability.objects.using('bot_db').filter(id=avail_id).first()
    if not a:
        messages.error(request, 'Disponibilidad no encontrada.')
        return redirect('dashboard:tutoring_schedule')
    if a.teacher_id != teacher['id']:
        messages.error(request, 'No tienes permiso para editar esta disponibilidad.')
        return redirect('dashboard:tutoring_schedule')
    if not form.is_valid():
        return _render_schedule(request, teacher, {
            'edit_availability_form': form,
            'show_edit_availability_modal': 'true',
            'edit_availability_id': avail_id,
        })
    st = form.cleaned_data['start_time']
    et = form.cleaned_data['end_time']
    day = a.day_of_week
    conflict = check_availability_overlap(teacher['id'], day, st, et, exclude_id=avail_id)
    if conflict:
        form.add_error(None, 'El intervalo se solapa con otro existente (%s - %s).' % (conflict.start_time.strftime('%H:%M'), conflict.end_time.strftime('%H:%M')))
        return _render_schedule(request, teacher, {
            'edit_availability_form': form,
            'show_edit_availability_modal': 'true',
            'edit_availability_id': avail_id,
        })
    try:
        a.start_time = st
        a.end_time = et
        a.save(using='bot_db')
        messages.success(request, 'Intervalo actualizado correctamente.')
    except Exception as e:
        logger.exception("Failed to update availability id=%s for teacher_id=%s", avail_id, teacher.get('id'))
        messages.error(request, f'Error al actualizar el intervalo: {e}')
    return redirect('dashboard:tutoring_schedule')

@require_POST
@login_required(login_url='dashboard:login')
def create_room(request):
    teacher = _get_teacher(request)
    form = CreateRoomForm(request.POST)
    selected_room_id = request.POST.get('selected_room_id')
    if not form.is_valid():
        data = get_data_for_dashboard(teacher, selected_room_id)
        return render(request, 'dashboard/dashboard.html', {
            'teacher': teacher,
            'courses': data['courses'],
            'selected_room': data['selected_room'],
            'selected_course': data['selected_course'],
            'students': data['selected_students'],
            'create_room_form': form,
            'show_create_modal': 'true',
        })
    course_id = form.cleaned_data['course_id']
    shortcode = (form.cleaned_data['shortcode'] or '').strip()
    topic = form.cleaned_data.get('topic')
    moodle_group = form.cleaned_data.get('moodle_group')
    auto_invite = form.cleaned_data.get('auto_invite', False)
    restrict_group = form.cleaned_data.get('restrict_group', False)
    try:
        # Prepare invite list synchronously (from dashboard/Moodle data)
        matrix_ids = []
        # Pre-fetch general room synchronously to avoid ORM calls inside async
        # General room is identified by teacher_id=None and shortcode == course shortname
        general = Room.objects.using('bot_db').filter(
            teacher_id=None,
            moodle_course_id=course_id,
            active=True,
        ).first()
        general_shortcode = ""
        if general:
            try:
                general_shortcode = (general.shortcode or '').strip()
            except Exception:
                general_shortcode = ""
        prefixed_shortcode = f"{general_shortcode}-{shortcode}" if general_shortcode else shortcode
        if auto_invite and moodle_group:
            # Pull users directly from Moodle for the selected course/group by name/id
            try:
                from .utils import fetch_moodle_groups, fetch_moodle_group_members, fetch_enrolled_students
                groups = fetch_moodle_groups(course_id) or []
                group_obj = next((g for g in groups if g.get('name') == moodle_group), None)
                if not group_obj:
                    try:
                        gid = int(moodle_group)
                        group_obj = next((g for g in groups if g.get('id') == gid), None)
                    except (ValueError, TypeError):
                        group_obj = None
                if not group_obj:
                    raise ValueError("Grupo no encontrado por nombre o ID")

                member_ids = fetch_moodle_group_members(group_obj['id']) or []
                enrolled = fetch_enrolled_students(course_id) or []
                # Students only (role shortname == 'student')
                group_enrolled = [s for s in enrolled if s.get('id') in member_ids and any(r.get('shortname') == 'student' for r in (s.get('roles') or []))]
                student_moodle_ids = [s.get('id') for s in group_enrolled if s.get('id') is not None]
                db_users = ExternalUser.objects.using('bot_db').filter(moodle_id__in=student_moodle_ids)
                for u in db_users:
                    if getattr(u, 'matrix_id', None):
                        matrix_ids.append(u.matrix_id)
            except Exception as e:
                logger.warning("Failed to fetch Moodle group users for course_id=%s group=%s: %s", course_id, moodle_group, e)
                messages.warning(request, f"No se pudieron obtener usuarios del grupo en Moodle: {e}")

        # Create Matrix room via async, then persist in DB synchronously, then invite
        async def _create_room_and_invite_async():
            general_room_id = general.room_id if general else None
            join_rule = None
            allowed_rooms = None
            if general_room_id:
                join_rule = "knock_restricted"
                allowed_rooms = [general_room_id]
            elif restrict_group:
                join_rule = "knock"
            new_room_id = await mc_create_room(
                prefixed_shortcode,
                topic or f"Grupo {prefixed_shortcode}",
                general_room_id=general_room_id,
                join_rule=join_rule,
                allowed_room_ids=allowed_rooms,
            )
            if matrix_ids:
                await invite_all_members(new_room_id, matrix_ids)
            # Always invite/join the teacher and grant moderator privileges
            try:
                teacher_mxid = teacher.get('matrix_id') if isinstance(teacher, dict) else None
                if teacher_mxid:
                    await join_user_admin(new_room_id, teacher_mxid)
                    try:
                        await set_user_power_level(new_room_id, teacher_mxid, 50)
                    except Exception as e:
                        logger.warning("Failed to grant moderator PL to teacher %s in room %s: %s", teacher_mxid, new_room_id, e)
            except Exception as e:
                logger.warning("Failed to join teacher %s to room %s: %s", teacher.get('matrix_id'), new_room_id, e)
            # Append invite link to the general room topic (same course, no moodle_group)
            try:
                if general and general.room_id:
                    # Ensure bot is joined to general room for state updates
                    if USERNAME:
                        try:
                            await join_user_admin(general.room_id, USERNAME)
                        except Exception as e:
                            logger.warning("Bot join to general room failed (room_id=%s): %s", general.room_id, e)
                            pass
                    await append_subgroup_link_to_topic(general.room_id, new_room_id, prefixed_shortcode)
            except Exception:
                logger.exception("Failed to update general room topic for course %s during subgroup creation", course_id)
                # Don't fail room creation if topic update fails
                pass
            return new_room_id

        new_room_id = async_to_sync(_create_room_and_invite_async)()

        room = Room.objects.using('bot_db').create(
            moodle_course_id=course_id,
            teacher_id=teacher['id'],
            shortcode=prefixed_shortcode,
            room_id=new_room_id,
            moodle_group=moodle_group if moodle_group and restrict_group else None,
        )
        messages.success(request, f"Sala '{prefixed_shortcode}' creada correctamente.")
        return redirect(f"{reverse('dashboard:dashboard')}?room_id={room.id}")
    except IntegrityError as e:
        if 'unique' in str(e).lower():
            form.add_error('shortcode', 'Ya existe una sala con este nombre.')
        else:
            form.add_error(None, f"Error al crear la sala: {e}")
        messages.error(request, f"Error de integridad al crear la sala: {e}")
    except Exception as e:
        logger.exception("Failed to create room for course_id=%s shortcode=%s", course_id, shortcode)
        form.add_error(None, f"Error al crear la sala: {e}")
        messages.error(request, f"Error al crear la sala: {e}")
    data = get_data_for_dashboard(teacher, selected_room_id)
    return render(request, 'dashboard/dashboard.html', {
        'teacher': teacher,
        'courses': data['courses'],
        'selected_room': data['selected_room'],
        'selected_course': data['selected_course'],
        'students': data['selected_students'],
        'create_room_form': form,
        'show_create_modal': 'true',
    })
    
@require_POST
@login_required(login_url='dashboard:login')
def deactivate_room(request, room_id):
    teacher = _get_teacher(request)
    if not teacher:
        return redirect('dashboard:login')
    room = get_object_or_404(Room.objects.using('bot_db'), id=room_id)
    if room.teacher_id != teacher['id']:
        messages.error(request, 'No tienes permiso para cerrar esta sala.')
        return redirect(f"{reverse('dashboard:dashboard')}?room_id={room.id}")
    # Perform Matrix-side deactivation behavior similar to setup script
    try:
        # Pre-fetch general room synchronously to avoid ORM calls inside async
        # General room is identified by teacher_id=None and shortcode == course shortname
        general = Room.objects.using('bot_db').filter(
            teacher_id=None,
            moodle_course_id=room.moodle_course_id,
            active=True,
        ).first()
        async def _deactivate():
            # Ensure bot is joined to the target room to mutate state
            try:
                if USERNAME:
                    await join_user_admin(room.room_id, USERNAME)
            except Exception as e:
                logger.warning("Bot join to target room failed (room_id=%s): %s", room.room_id, e)
                pass
            # Prefix room name with academic CLOSED
            created_at = room.get_created_at_aware()
            prefix = academic_closed_prefix(created_at)
            await ensure_room_name_prefixed(room.room_id, prefix)
            # Silence members (PL=-10)
            await silence_room_members(room.room_id)
            # Cancel any pending invites
            await cancel_pending_invites(room.room_id)
            # Remove invite link from general room topic
            try:
                if general and general.room_id:
                    # Ensure bot joined before updating topic
                    if USERNAME:
                        try:
                            await join_user_admin(general.room_id, USERNAME)
                        except Exception as e:
                            logger.warning("Bot join to general room failed (room_id=%s): %s", general.room_id, e)
                            pass
                    await remove_subgroup_link_from_topic(general.room_id, room.room_id, room.shortcode)
            except Exception:
                logger.exception("Failed to update general room topic during room deactivation (room_id=%s)", room.room_id)
                # Swallow topic update errors; continue deactivation
                pass
        async_to_sync(_deactivate)()
    except Exception as e:
        logger.exception("Matrix-side deactivation steps failed for room_id=%s", room.room_id)
        messages.warning(request, f"No se pudo aplicar cierre en Matrix: {e}")
    # Mark inactive in DB
    room.active = False
    room.save(using='bot_db')
    messages.success(request, f"La sala '{room.shortcode}' ha sido cerrada correctamente (DB + Matrix).")
    return redirect('dashboard:dashboard')


@require_POST
@login_required(login_url='dashboard:login')
def create_question(request):
    teacher = _get_teacher(request)
    if not teacher:
        return redirect('dashboard:login')
    form = CreateQuestionForm(request.POST)
    selected_room_id = request.POST.get('selected_room_id')
    if not form.is_valid():
        data = get_data_for_dashboard(teacher, selected_room_id)
        return render(request, 'dashboard/dashboard.html', {
            'teacher': teacher,
            'courses': data['courses'],
            'selected_room': data['selected_room'],
            'selected_course': data['selected_course'],
            'students': data['selected_students'],
            'create_question_form': form,
            'show_create_question_modal': 'true',
        })
    room = None
    if selected_room_id:
        room = Room.objects.using('bot_db').filter(id=selected_room_id).first()
    if not room or room.teacher_id != teacher['id']:
        messages.error(request, 'No tienes permiso para añadir preguntas en esta sala.')
        return redirect(f"{reverse('dashboard:dashboard')}?room_id={selected_room_id}")
    options_map = {}
    for key, val in request.POST.items():
        if key.startswith('option_') and val and val.strip():
            try:
                idx = int(key.split('_', 1)[1])
            except Exception:
                continue
            options_map[idx] = val.strip()
    options = [options_map[i] for i in sorted(options_map.keys())]
    qtype = form.cleaned_data.get('qtype')
    if qtype == 'multiple_choice':
        single_choice = request.POST.get('option_correct_single')
        any_correct = False
        if single_choice is not None and single_choice != '':
            any_correct = True
        else:
            for idx in range(len(options)):
                if request.POST.get(f'option_correct_{idx}'):
                    any_correct = True
                    break
        if not any_correct:
            form.add_error(None, 'Debe marcar al menos una opción como correcta para preguntas de opción múltiple.')
            data = get_data_for_dashboard(teacher, selected_room_id)
            return render(request, 'dashboard/dashboard.html', {
                'teacher': teacher,
                'courses': data['courses'],
                'selected_room': data['selected_room'],
                'selected_course': data['selected_course'],
                'students': data['selected_students'],
                'create_question_form': form,
                'show_create_question_modal': 'true',
            })
    try:
        q = Question.objects.using('bot_db').create(
            teacher_id=teacher['id'],
            room_id=room.id,
            title=form.cleaned_data.get('title') or None,
            body=form.cleaned_data['body'],
            qtype=qtype,
            start_at=form.cleaned_data.get('start_at'),
            end_at=form.cleaned_data.get('end_at'),
            manual_active=False,
            allow_multiple_submissions=form.cleaned_data.get('allow_multiple_submissions', False),
            allow_multiple_answers=form.cleaned_data.get('allow_multiple_answers', False),
            close_on_first_correct=form.cleaned_data.get('close_on_first_correct', False)
        )
        if qtype in ('short_answer', 'numeric'):
            expected = request.POST.get('expected_answer', '').strip()
            if expected:
                QuestionOption.objects.using('bot_db').create(
                    question_id=q.id,
                    option_key='ANSWER',
                    text=expected,
                    is_correct=True,
                    position=0
                )
        elif qtype == 'true_false':
            tf_correct = request.POST.get('tf_correct')
            for idx, opt_text in enumerate(options):
                is_correct = (str(idx) == str(tf_correct)) if tf_correct is not None else False
                # Use 'V' for Verdadero (True) and 'F' for Falso (False)
                option_key = 'V' if idx == 0 else 'F'
                QuestionOption.objects.using('bot_db').create(
                    question_id=q.id,
                    option_key=option_key,
                    text=opt_text,
                    is_correct=is_correct,
                    position=idx
                )
        elif qtype == 'multiple_choice':
            single_choice = request.POST.get('option_correct_single')
            for idx, opt_text in enumerate(options):
                if single_choice is not None and single_choice != '':
                    is_correct = (str(idx) == str(single_choice))
                else:
                    correct_flag = request.POST.get(f'option_correct_{idx}')
                    is_correct = bool(correct_flag)
                QuestionOption.objects.using('bot_db').create(
                    question_id=q.id,
                    option_key=chr(65 + (idx % 26)),
                    text=opt_text,
                    is_correct=is_correct,
                    position=idx
                )
        elif qtype == 'poll':
            # Poll behaves like multiple choice but there are no correct options
            for idx, opt_text in enumerate(options):
                QuestionOption.objects.using('bot_db').create(
                    question_id=q.id,
                    option_key=chr(65 + (idx % 26)),
                    text=opt_text,
                    is_correct=False,
                    position=idx
                )
        messages.success(request, 'Pregunta creada correctamente.')
        return redirect(f"{reverse('dashboard:dashboard')}?room_id={room.id}")
    except Exception as e:
        logger.exception("Failed to create question in room_id=%s by teacher_id=%s", getattr(room, 'id', None), teacher.get('id'))
        form.add_error(None, f"Error creando la pregunta: {e}")
        data = get_data_for_dashboard(teacher, selected_room_id)
        return render(request, 'dashboard/dashboard.html', {
            'teacher': teacher,
            'courses': data['courses'],
            'selected_room': data['selected_room'],
            'selected_course': data['selected_course'],
            'students': data['selected_students'],
            'create_question_form': form,
            'show_create_question_modal': 'true',
        })


@require_POST
@login_required(login_url='dashboard:login')
def toggle_question_active(request, question_id):
    teacher = _get_teacher(request)
    if not teacher:
        return redirect('dashboard:login')
    q = Question.objects.using('bot_db').filter(id=question_id).first()
    if not q:
        messages.error(request, 'Pregunta no encontrada.')
        return redirect('dashboard:dashboard')
    if q.teacher_id != teacher['id']:
        messages.error(request, 'No tienes permiso para modificar esta pregunta.')
        return redirect('dashboard:dashboard')
    now = timezone.now()
    try:
        if getattr(q, 'close_on_first_correct', False) and getattr(q, 'close_triggered', False):
            messages.error(request, 'Esta pregunta fue cerrada tras recibir la primera respuesta correcta y no se puede reabrir desde aquí.')
            return redirect(f"{reverse('dashboard:dashboard')}?room_id={q.room_id}")
        if q.start_at is None and q.end_at is None:
            q.manual_active = not bool(q.manual_active)
            q.save(using='bot_db')
            messages.success(request, f"Campo manual_active actualizado (ahora={'sí' if q.manual_active else 'no'}).")
            return redirect(f"{reverse('dashboard:dashboard')}?room_id={q.room_id}")
        if q.end_at is not None and q.end_at < now:
            q.manual_active = not bool(q.manual_active)
            q.save(using='bot_db')
            messages.success(request, f"Campo manual_active actualizado (ahora={'sí' if q.manual_active else 'no'}).")
            return redirect(f"{reverse('dashboard:dashboard')}?room_id={q.room_id}")
        within_window = True
        try:
            within_window = (
                (q.start_at is None or now >= q.start_at) and (q.end_at is None or now <= q.end_at)
            )
        except Exception:
            within_window = True
        if within_window:
            q.end_at = now
            q.manual_active = False
            q.save(using='bot_db')
            messages.success(request, 'Pregunta finalizada ahora (end_at actualizada).')
            return redirect(f"{reverse('dashboard:dashboard')}?room_id={q.room_id}")
        q.start_at = now
        q.manual_active = False
        q.save(using='bot_db')
        messages.success(request, 'Pregunta iniciada ahora (start_at actualizada).')
    except Exception as e:
        logger.exception("Failed to toggle question_active for question_id=%s", question_id)
        messages.error(request, f"Error al actualizar la pregunta: {e}")
    return redirect(f"{reverse('dashboard:dashboard')}?room_id={q.room_id}")



@require_POST
@login_required(login_url='dashboard:login')
def delete_question(request, question_id):
    teacher = _get_teacher(request)
    if not teacher:
        return redirect('dashboard:login')
    q = Question.objects.using('bot_db').filter(id=question_id).first()
    if not q:
        messages.error(request, 'Pregunta no encontrada.')
        return redirect('dashboard:dashboard')
    if q.teacher_id != teacher['id']:
        messages.error(request, 'No tienes permiso para eliminar esta pregunta.')
        return redirect('dashboard:dashboard')
    try:
        q.delete(using='bot_db')
        messages.success(request, 'Pregunta eliminada correctamente.')
    except Exception as e:
        logger.exception("Failed to delete question_id=%s by teacher_id=%s", question_id, teacher.get('id'))
        messages.error(request, f"Error al eliminar la pregunta: {e}")
    return redirect(f"{reverse('dashboard:dashboard')}?room_id={q.room_id}")


@require_POST
@login_required(login_url='dashboard:login')
def grade_response(request, response_id):
    teacher = _get_teacher(request)
    if not teacher:
        return redirect('dashboard:login')
    resp = QuestionResponse.objects.using('bot_db').filter(id=response_id).first()
    if not resp:
        messages.error(request, 'Respuesta no encontrada.')
        return redirect('dashboard:dashboard')
    # check that the teacher owns the question
    q = Question.objects.using('bot_db').filter(id=resp.question_id).first()
    if not q or q.teacher_id != teacher['id']:
        messages.error(request, 'No tienes permiso para corregir esta respuesta.')
        return redirect('dashboard:dashboard')

    if request.method == 'POST':
        form = GradeResponseForm(request.POST)
        if not form.is_valid():
            # re-render dashboard with modal open and form errors
            data = get_data_for_dashboard(teacher, q.room_id)
            return render(request, 'dashboard/dashboard.html', {
                'teacher': teacher,
                'courses': data['courses'],
                'selected_room': data['selected_room'],
                'selected_course': data['selected_course'],
                'students': data['selected_students'],
                'questions_list': data.get('selected_questions', []),
                'grade_response_form': form,
                'show_grade_response_modal': 'true',
                'grade_response_id': response_id,
                'grade_response_score': request.POST.get('score', ''),
                'grade_response_feedback': request.POST.get('feedback', ''),
                'selected_page': 'dashboard',
            })

        try:
            score = form.cleaned_data.get('score')
            feedback = form.cleaned_data.get('feedback') or None
            resp.score = float(score) if score is not None else None
            resp.feedback = feedback
            resp.is_graded = True
            resp.grader_id = teacher['id']
            resp.save(using='bot_db')
            messages.success(request, 'Respuesta corregida correctamente.')
        except Exception as e:
            logger.exception("Failed to save grade for response_id=%s by teacher_id=%s", response_id, teacher.get('id'))
            messages.error(request, f'Error al guardar la corrección: {e}')
    return redirect(f"{reverse('dashboard:dashboard')}?room_id={q.room_id}")