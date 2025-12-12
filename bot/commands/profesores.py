from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from config import DB_TYPE
from core.db.constants import (
    COL_ROOM_SHORTCODE,
    COL_USER_ID,
    COL_USER_MATRIX_ID,
    COL_USER_MOODLE_ID,
    get_db_modules,
)
from core.moodle import fetch_course_teachers, fetch_user_courses

USAGE = "!profesores"
DESCRIPTION = "Lista profesores y salas activas por curso en los que estás matriculado."


def _matrix_localpart(matrix_id: Optional[str]) -> str:
    if not matrix_id:
        return "No registrado"
    local = matrix_id.split(":", 1)[0]
    return local.lstrip("@") or "No registrado"


async def run(client, room_id, event, args):
    db = get_db_modules()[DB_TYPE]["queries"]

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

    courses = await fetch_user_courses(moodle_user_id)
    if not courses:
        await client.send_text(room_id, "❌ No se encontraron asignaturas en Moodle para tu usuario.")
        return

    teacher_cache: Dict[int, Optional[Dict[str, object]]] = {}
    rooms_cache: Dict[Tuple[int, int], List[Dict[str, object]]] = {}

    lines: List[str] = []
    teachers_listed = False

    for course in courses:
        course_id = course.get("id")
        if course_id is None:
            continue
        try:
            int_course_id = int(course_id)
        except (TypeError, ValueError):
            continue

        course_name = str(
            course.get("fullname")
            or course.get("displayname")
            or course.get("shortname")
            or f"Curso {int_course_id}"
        )
        course_lines: List[str] = [f"📚 {course_name}"]

        teachers = await fetch_course_teachers(int_course_id)
        if not teachers:
            course_lines.append("    • Sin profesores disponibles.")
            lines.extend(course_lines + [""])
            continue

        seen_teachers: set[int] = set()
        for teacher in teachers:
            teacher_moodle_id = teacher.get("id")
            if teacher_moodle_id is None:
                continue
            try:
                teacher_moodle_id = int(teacher_moodle_id)
            except (TypeError, ValueError):
                continue
            if teacher_moodle_id in seen_teachers:
                continue
            seen_teachers.add(teacher_moodle_id)

            teacher_name = str(
                teacher.get("fullname")
                or teacher.get("displayname")
                or teacher.get("firstname")
                or f"Profesor {teacher_moodle_id}"
            )
            course_lines.append(f"  • {teacher_name}")
            teachers_listed = True

            if teacher_moodle_id not in teacher_cache:
                teacher_record = await db.get_user_by_moodle_id(teacher_moodle_id)
                teacher_cache[teacher_moodle_id] = dict(teacher_record) if teacher_record else None
            teacher_info = teacher_cache[teacher_moodle_id]

            matrix_username = "No registrado"
            rooms_summary = "Ninguna sala activa asociada."

            if teacher_info:
                teacher_db_id = teacher_info.get(COL_USER_ID)
                matrix_username = _matrix_localpart(teacher_info.get(COL_USER_MATRIX_ID))
                if isinstance(teacher_db_id, int):
                    cache_key = (int_course_id, teacher_db_id)
                    if cache_key not in rooms_cache:
                        rooms_cache[cache_key] = await db.get_active_rooms_for_teacher_and_course(
                            int_course_id, teacher_db_id
                        )
                    rooms_data = rooms_cache.get(cache_key) or []
                    room_names = [
                        str(room.get(COL_ROOM_SHORTCODE))
                        for room in rooms_data
                        if room.get(COL_ROOM_SHORTCODE)
                    ]
                    if room_names:
                        rooms_summary = ", ".join(room_names)

            course_lines.append(f"      ▹ Salas: {rooms_summary}")
            course_lines.append(f"      ▹ Matrix: {matrix_username}")

        lines.extend(course_lines + [""])

    if not teachers_listed and not lines:
        await client.send_text(room_id, "❌ No se encontraron profesores para tus asignaturas.")
        return

    if lines and lines[-1] == "":
        lines.pop()

    await client.send_text(
        room_id,
        "\n".join(["📋 Profesores matriculados:"] + lines),
    )
