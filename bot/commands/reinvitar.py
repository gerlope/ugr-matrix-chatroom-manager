# commands/reinvitar.py
"""
Invita al usuario a todas las salas generales de los cursos donde está matriculado
en Moodle y aún no está unido.
"""
from __future__ import annotations

from typing import List, Dict

from config import DB_TYPE
from core.db.constants import (
    COL_ROOM_ROOM_ID,
    COL_ROOM_SHORTCODE,
    COL_ROOM_MOODLE_COURSE_ID,
    COL_USER_MOODLE_ID,
    COL_USER_IS_TEACHER,
    get_db_modules,
)
from core.moodle import fetch_user_courses

USAGE = "!reinvitar"
DESCRIPTION = "Te invita a las salas generales de tus cursos de Moodle y muestra enlaces."


def _build_matrix_link(room_id: str) -> str:
    return f"https://matrix.to/#/{room_id}"


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

    # Build course_id -> course_name mapping
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
            course.get("fullname")
            or course.get("displayname")
            or course.get("shortname")
            or f"Curso {int_cid}"
        )

    if not course_ids:
        await client.send_text(room_id, "❌ No se encontraron cursos válidos en Moodle.")
        return

    general_rooms = await db.get_general_rooms_for_courses(course_ids)
    if not general_rooms:
        await client.send_text(
            room_id,
            "ℹ️ No hay salas generales registradas para tus cursos de Moodle.",
        )
        return

    # Check if user is a teacher
    caller_is_teacher = bool(user_row.get(COL_USER_IS_TEACHER))

    # Filter out _teachers rooms unless the caller is a teacher
    if not caller_is_teacher:
        general_rooms = [
            r for r in general_rooms
            if not (r.get(COL_ROOM_SHORTCODE) or "").endswith("_teachers")
        ]
        if not general_rooms:
            await client.send_text(
                room_id,
                "ℹ️ No hay salas generales (no de profesores) registradas para tus cursos.",
            )
            return

    invited_count = 0
    already_in_count = 0
    invite_errors: List[str] = []
    room_links: List[str] = []

    async def is_user_in_room(room: str, user: str) -> bool:
        """Check if user is already a member (join or invite) of the room."""
        try:
            member_event = await client.get_state_event(room, "m.room.member", user)
            if member_event:
                membership = member_event.get("membership", "")
                return membership in ("join", "invite")
        except Exception:
            pass
        return False

    for room_data in general_rooms:
        target_room_id = room_data[COL_ROOM_ROOM_ID]
        shortcode = room_data.get(COL_ROOM_SHORTCODE, "Sala general")
        course_id = room_data.get(COL_ROOM_MOODLE_COURSE_ID)
        course_label = course_names.get(course_id, f"Curso {course_id}") if course_id else shortcode

        link = _build_matrix_link(target_room_id)
        room_links.append(f"• {course_label}: {link}")

        # Check if user is already in the room using room state
        if await is_user_in_room(target_room_id, event.sender):
            already_in_count += 1
            continue

        try:
            await client.invite_user(target_room_id, event.sender)
            invited_count += 1
        except Exception as exc:
            error_msg = str(exc)
            if "already in the room" in error_msg.lower():
                already_in_count += 1
            else:
                invite_errors.append(f"{shortcode}: {error_msg}")

    # Build summary
    summary_parts = []
    if invited_count > 0:
        summary_parts.append(f"✅ Se enviaron {invited_count} invitación(es) nueva(s).")
    if already_in_count > 0:
        summary_parts.append(f"ℹ️ Ya estabas en {already_in_count} sala(s).")
    if invite_errors:
        summary_parts.append(f"⚠️ Errores en {len(invite_errors)} sala(s): " + "; ".join(invite_errors[:3]))

    links_text = "\n".join(room_links)
    message = (
        "📋 Salas generales de tus cursos:\n"
        f"{links_text}\n\n"
        + "\n".join(summary_parts)
    )
    await client.send_text(room_id, message)
