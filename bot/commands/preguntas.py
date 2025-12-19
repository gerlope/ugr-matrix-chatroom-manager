# commands/preguntas.py
"""
Muestra las preguntas activas para los cursos en los que el usuario está matriculado.
Solo muestra preguntas de salas sin grupo asignado o de grupos en los que el usuario está.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set

from config import DB_TYPE
from core.db.constants import (
    COL_QUESTION_ID,
    COL_QUESTION_TITLE,
    COL_QUESTION_BODY,
    COL_QUESTION_QTYPE,
    COL_QUESTION_END_AT,
    COL_QUESTION_ALLOW_MULTIPLE_SELECTIONS,
    COL_QUESTION_ALLOW_MULTIPLE_SUBMISSIONS,
    COL_QUESTION_CLOSE_ON_FIRST_CORRECT,
    COL_QUESTION_ALLOW_LATE,
    COL_USER_MOODLE_ID,
    get_db_modules,
)
from core.moodle import fetch_user_courses, fetch_user_groups_in_course

USAGE = "!preguntas"
DESCRIPTION = "Muestra las preguntas activas de tus cursos."


QTYPE_LABELS = {
    "multiple_choice": "📝 Test/Multiple selección",
    "poll": "📊 Encuesta",
    "true_false": "✅ Verdadero/Falso",
    "short_answer": "✍️ Respuesta corta",
    "numeric": "🔢 Numérico",
    "essay": "📄 Ensayo",
}


async def run(client, room_id, event, args):
    db = get_db_modules()[DB_TYPE]["queries"]

    # Get user info
    user_row = await db.get_user_by_matrix_id(event.sender)
    if not user_row:
        await client.send_text(room_id, "❌ No estás registrado en la base de datos.")
        return

    user_moodle_id = user_row[COL_USER_MOODLE_ID]
    try:
        moodle_user_id = int(user_moodle_id)
    except (TypeError, ValueError):
        await client.send_text(room_id, "❌ Tu registro no tiene un Moodle ID válido.")
        return

    # Get user's courses
    courses = await fetch_user_courses(moodle_user_id)
    if not courses:
        await client.send_text(room_id, "❌ No se encontraron asignaturas en Moodle para tu usuario.")
        return

    # Build course_id list and name mapping
    course_ids: List[int] = []
    course_names: Dict[int, str] = {}
    for course in courses:
        cid = course.get("id")
        if cid is None:
            continue
        try:
            int_cid = int(cid)
        except (TypeError, ValueError):
            continue
        course_ids.append(int_cid)
        course_names[int_cid] = str(
            course.get("shortname")
            or course.get("fullname")
            or course.get("displayname")
            or f"Curso {int_cid}"
        )

    if not course_ids:
        await client.send_text(room_id, "❌ No se encontraron cursos válidos en Moodle.")
        return

    # Get active questions for these courses
    questions = await db.get_active_questions_for_courses(course_ids)
    if not questions:
        await client.send_text(room_id, "ℹ️ No hay preguntas activas en tus cursos.")
        return

    # Get user's groups for each course (to filter by moodle_group)
    user_groups_by_course: Dict[int, Set[str]] = {}
    courses_needing_groups = set()
    for q in questions:
        if q.get("room_moodle_group"):
            courses_needing_groups.add(q.get("room_course_id"))

    for cid in courses_needing_groups:
        groups = await fetch_user_groups_in_course(cid, moodle_user_id)
        user_groups_by_course[cid] = set(groups)

    # Filter questions: include if room has no group OR user is in that group
    filtered_questions = []
    for q in questions:
        room_group = q.get("room_moodle_group")
        course_id = q.get("room_course_id")
        if room_group:
            user_groups = user_groups_by_course.get(course_id, set())
            if room_group not in user_groups:
                continue
        filtered_questions.append(q)

    if not filtered_questions:
        await client.send_text(room_id, "ℹ️ No hay preguntas activas en tus cursos/grupos.")
        return

    # Organize questions by room
    questions_by_room: Dict[str, List[dict]] = defaultdict(list)
    for q in filtered_questions:
        room_key = q.get("room_shortcode") or q.get("room_matrix_id") or "Sala desconocida"
        questions_by_room[room_key].append(q)

    # Fetch options for each question
    question_options: Dict[int, List[dict]] = {}
    for q in filtered_questions:
        qid = q.get("id")
        if qid:
            options = await db.get_question_options(qid)
            question_options[qid] = options

    # Build output message
    total_count = len(filtered_questions)
    lines = [f"📋 Preguntas activas ({total_count})\n"]

    for room_name, room_questions in questions_by_room.items():
        lines.append("─" * 25)
        lines.append(f"🏠 {room_name}")
        lines.append("─" * 25)
        
        for q in room_questions:
            qid = q.get(COL_QUESTION_ID)
            title = q.get(COL_QUESTION_TITLE) or "(Sin título)"
            body = q.get(COL_QUESTION_BODY) or ""
            qtype = q.get(COL_QUESTION_QTYPE) or "unknown"
            qtype_label = QTYPE_LABELS.get(qtype, f"📌 {qtype}")
            flags = []
            
            lines.append(f"\n  🔹 #{qid} │ {title}")
            
            # Behaviour indicators
            flags.append(qtype_label)
            if q.get(COL_QUESTION_ALLOW_MULTIPLE_SELECTIONS):
                flags.append("✅ Multiple selección")
            if q.get(COL_QUESTION_ALLOW_MULTIPLE_SUBMISSIONS):
                flags.append("🔁 Permite múltiples envíos")
            if q.get(COL_QUESTION_CLOSE_ON_FIRST_CORRECT):
                flags.append("🏁 Cierra al primer acierto")
            if q.get(COL_QUESTION_ALLOW_LATE):
                flags.append("⏰ Permite tardías")
            if flags:
                lines.append(f"     {' · '.join(flags)}")
                
            # Closing timestamp
            end_at = q.get(COL_QUESTION_END_AT)
            if end_at:
                try:
                    if hasattr(end_at, "strftime"):
                        end_txt = end_at.strftime("%Y-%m-%d %H:%M")
                    else:
                        end_txt = str(end_at)
                except Exception:
                    end_txt = str(end_at)
                lines.append(f"     ⏰ Cierre: {end_txt}")
                
            if body:
                # Indent multi-line body
                body_lines = body.strip().split("\n")
                lines.append("\n     📄 Enunciado:")
                for bl in body_lines:
                    lines.append(f"     {bl}")

            options = question_options.get(qid, [])
            if options:
                lines.append("")
                for opt in options:
                    opt_key = opt.get("option_key", "?")
                    opt_text = opt.get("text", "")
                    lines.append(f"       {opt_key}) {opt_text}")
            lines.append("")  # Extra newline after each question

    lines.append("━" * 30)
    lines.append("💡 Responde por mensaje directo al bot con !responder <ID> <respuesta>|<opcion 1> [<opcion 2> ...].")

    message = "\n".join(lines)
    await client.send_text(room_id, message)
