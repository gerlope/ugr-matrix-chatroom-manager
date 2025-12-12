from __future__ import annotations

from typing import Tuple

from config import DB_TYPE, SERVER_NAME
from core.db.constants import (
    COL_ROOM_ROOM_ID,
    COL_ROOM_SHORTCODE,
    COL_USER_ID,
    COL_USER_IS_TEACHER,
    get_db_modules,
)
from core.tutoring_queue import tutoring_queue

USAGE = "!tutoria <profesor>|confirmar <profesor>|liberar <profesor>|salir <profesor>|estado <profesor>\n Encuentra <profesor> en el comando !profesores."
DESCRIPTION = "Gestiona la cola de tutorías individuales por profesor."

SUBCOMMANDS = {"confirmar", "liberar", "salir", "estado"}


def _normalize_teacher_identifier(raw: str) -> Tuple[str, str]:
    data = (raw or "").strip()
    if not data:
        return "", ""
    if data.startswith("@"):
        local = data.split(":", 1)[0].lstrip("@")
        domain = data.split(":", 1)[1] if ":" in data else SERVER_NAME
        return f"@{local}:{domain}", local
    local = data
    return f"@{local}:{SERVER_NAME}", local


def _localpart(mxid: str) -> str:
    return mxid.split(":", 1)[0].lstrip("@")


async def run(client, room_id, event, args):
    if not args:
        await client.send_text(room_id, f"⚠️ Uso: {USAGE}")
        return

    db = get_db_modules()[DB_TYPE]["queries"]

    action = args[0].lower()
    if action in SUBCOMMANDS:
        if len(args) < 2:
            await client.send_text(room_id, f"⚠️ Debes indicar el profesor: {USAGE}")
            return
        teacher_arg = args[1]
    else:
        teacher_arg = action
        action = "solicitar"

    teacher_mxid, teacher_local = _normalize_teacher_identifier(teacher_arg)
    if not teacher_mxid:
        await client.send_text(room_id, "❌ Identificador de profesor inválido.")
        return

    teacher_row = await db.get_user_by_matrix_id(teacher_mxid)
    if not teacher_row or not teacher_row[COL_USER_IS_TEACHER]:
        await client.send_text(room_id, "❌ No se encontró un profesor con ese Matrix ID.")
        return

    teacher_id = teacher_row[COL_USER_ID]
    tutoring_room = await db.get_teacher_tutoring_room(teacher_id)
    if not tutoring_room:
        await client.send_text(room_id, "❌ Ese profesor no tiene una sala de tutoría registrada.")
        return

    target_room_id = tutoring_room[COL_ROOM_ROOM_ID]
    room_label = tutoring_room.get(COL_ROOM_SHORTCODE, "Sala de tutoría")

    if action == "solicitar":
        position, added = await tutoring_queue.enqueue(
            room_id=target_room_id,
            teacher_mxid=teacher_mxid,
            teacher_label=room_label,
            teacher_localpart=teacher_local,
            user_mxid=event.sender,
            notify_room_id=room_id,
        )
        if added:
            await client.send_text(
                room_id,
                (
                    f"✅ Te has unido a la cola de {room_label}. "
                    f"Posición actual: {position}.\n"
                    "Recibirás un aviso cuando la sala esté libre."
                ),
            )
        else:
            await client.send_text(
                room_id,
                f"ℹ️ Ya estabas en la cola de {room_label}. Posición actual: {position}.",
            )
        return

    if action == "confirmar":
        ok, detail = await tutoring_queue.confirm_access(target_room_id, event.sender)
        if ok:
            invite_error = None
            try:
                await client.invite_user(target_room_id, event.sender)
            except Exception as exc:
                invite_error = str(exc)
            await client.send_text(
                room_id,
                (
                    f"🚪 Acceso confirmado. Se le ha invitado a la sala {room_label}. La sala de {room_label} queda ocupada hasta que quede libre."
                    + (f"\n⚠️ No se pudo enviar la invitación automática: {invite_error}" if invite_error else "")
                ),
            )
        else:
            await client.send_text(room_id, f"❌ {detail}")
        return

    if action == "liberar":
        sender_is_teacher = event.sender == teacher_mxid
        if not sender_is_teacher:
            is_active = await tutoring_queue.is_active_user(target_room_id, event.sender)
            if not is_active:
                await client.send_text(
                    room_id,
                    "❌ Solo el profesor o la persona atendida pueden liberar la sala.",
                )
                return
        ok, detail = await tutoring_queue.release_current(target_room_id)
        if ok:
            released_user = _localpart(detail) if detail else None
            tail = (
                f"Se notificará a la siguiente persona (sale {released_user})."
                if released_user
                else "Cola vacía por ahora."
            )
            await client.send_text(
                room_id,
                f"✅ Sala liberada. {tail}",
            )
        else:
            await client.send_text(room_id, f"❌ {detail}")
        return

    if action == "salir":
        removed = await tutoring_queue.leave_queue(target_room_id, event.sender)
        if removed:
            await client.send_text(
                room_id,
                f"✅ Saliste de la cola de {room_label}.",
            )
        else:
            await client.send_text(room_id, "ℹ️ No estabas en la cola de esa sala.")
        return

    if action == "estado":
        snapshot = await tutoring_queue.get_snapshot(target_room_id)
        entries = snapshot.get("entries", [])
        if not entries:
            await client.send_text(
                room_id,
                f"📊 Cola vacía para {room_label} (estado: {snapshot.get('state')}).",
            )
            return
        lines = [f"📊 Estado de {room_label}: {snapshot.get('state')}"]
        for item in entries:
            user_alias = _localpart(item["user_mxid"])
            status = item["status"]
            lines.append(f"  • {item['position']}. {user_alias} — {status}")
        await client.send_text(room_id, "\n".join(lines))
        return

    await client.send_text(room_id, f"⚠️ Uso: {USAGE}")
