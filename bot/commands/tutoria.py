from __future__ import annotations

from datetime import datetime, time
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

USAGE = "!tutoria [confirmar|acabar|salir|estado] <profesor>"
DESCRIPTION = "Gestiona tutorías individuales. Encuentra <profesor> en el comando !profesores"

SUBCOMMANDS = {"confirmar", "acabar", "salir", "estado"}

WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
WEEKDAY_TO_INDEX = {name: idx for idx, name in enumerate(WEEKDAY_NAMES)}
WEEKDAY_LABELS_ES = {
    "Monday": "lunes",
    "Tuesday": "martes",
    "Wednesday": "miércoles",
    "Thursday": "jueves",
    "Friday": "viernes",
    "Saturday": "sábado",
    "Sunday": "domingo",
}


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


def _coerce_time(value):
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
    return value


def _format_slot(entry) -> str:
    start = _coerce_time(entry["start_time"])
    end = _coerce_time(entry["end_time"])
    start_txt = start.strftime("%H:%M") if hasattr(start, "strftime") else str(start)
    end_txt = end.strftime("%H:%M") if hasattr(end, "strftime") else str(end)
    return f"{start_txt}-{end_txt}"


async def _is_teacher_available_now(db_module, teacher_id: int) -> Tuple[bool, str | None]:
    windows = await db_module.get_teacher_availability_windows(teacher_id)
    if not windows:
        return False, f"❌ Este profesor no ha configurado un horario para tutorías"

    normalized = [
        {
            "day_of_week": entry["day_of_week"],
            "start_time": _coerce_time(entry["start_time"]),
            "end_time": _coerce_time(entry["end_time"]),
        }
        for entry in windows
    ]

    now = datetime.now().astimezone()
    current_day_name = WEEKDAY_NAMES[now.weekday()]
    current_time = now.time()
    if current_time.tzinfo:
        current_time = current_time.replace(tzinfo=None)

    todays = [entry for entry in normalized if entry["day_of_week"] == current_day_name]
    for entry in todays:
        if entry["start_time"] <= current_time < entry["end_time"]:
            return True, None

    if todays:
        slots = ", ".join(_format_slot(entry) for entry in todays)
        return False, (
            f"❌ Ese profesor solo atiende hoy entre {slots}. "
            "Intenta dentro de su horario disponible."
        )

    next_window = None
    for entry in normalized:
        day_idx = WEEKDAY_TO_INDEX.get(entry["day_of_week"])
        if day_idx is None:
            continue
        delta_days = (day_idx - now.weekday()) % 7
        if delta_days == 0 and entry["start_time"] <= current_time:
            delta_days = 7
        if not next_window:
            next_window = (delta_days, entry)
            continue
        if delta_days < next_window[0]:
            next_window = (delta_days, entry)
            continue
        if delta_days == next_window[0] and entry["start_time"] < next_window[1]["start_time"]:
            next_window = (delta_days, entry)

    if next_window:
        delta_days, entry = next_window
        slot = _format_slot(entry)
        day_name = entry["day_of_week"]
        if delta_days == 0:
            day_hint = "hoy"
        elif delta_days == 1:
            day_hint = "mañana"
        elif delta_days >= 7:
            day_hint = f"el {WEEKDAY_LABELS_ES.get(day_name, day_name)} de la proxima semana"
        else:
            day_hint = f"el {WEEKDAY_LABELS_ES.get(day_name, day_name)}"
        return False, f"❌ El profesor no está disponible ahora. Próxima franja {day_hint}: {slot}."

    return False, "❌ No fue posible comprobar la disponibilidad del profesor."


async def run(client, room_id, event, args):
    if not args:
        await client.send_text(room_id, f"⚠️ Uso: {USAGE}")
        return

    db = get_db_modules()[DB_TYPE]["queries"]

    action = args[0].lower()
    implicit_teacher = False
    if action in SUBCOMMANDS:
        if len(args) >= 2:
            teacher_arg = args[1]
        elif action in {"acabar", "estado", "confirmar"}:
            teacher_arg = _localpart(event.sender)
            implicit_teacher = True
        else:
            await client.send_text(room_id, f"⚠️ Debes indicar el profesor: {USAGE}")
            return
    else:
        teacher_arg = action
        action = "solicitar"

    teacher_mxid, teacher_local = _normalize_teacher_identifier(teacher_arg)
    if not teacher_mxid:
        await client.send_text(room_id, "❌ Identificador de profesor inválido.")
        return

    teacher_row = await db.get_user_by_matrix_id(teacher_mxid)
    if not teacher_row or not teacher_row[COL_USER_IS_TEACHER]:
        if implicit_teacher:
            await client.send_text(
                room_id,
                "❌ Solo un profesor registrado puede usar ese comando sin especificar a quién se refiere.",
            )
        else:
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
        if event.sender == teacher_mxid:
            await client.send_text(
                room_id,
                "❌ Un profesor no puede solicitarse a sí mismo. Usa \"acabar\" si necesitas liberar la sala.",
            )
            return
        allowed, warning = await _is_teacher_available_now(db, teacher_id)
        if not allowed:
            await client.send_text(room_id, warning or "❌ Ese profesor no está disponible ahora.")
            return
        position, added, auto_confirm = await tutoring_queue.enqueue(
            room_id=target_room_id,
            teacher_mxid=teacher_mxid,
            teacher_label=room_label,
            teacher_localpart=teacher_local,
            user_mxid=event.sender,
            notify_room_id=room_id,
        )
        if added and auto_confirm:
            # Queue was free and user is first - auto-confirm their spot
            ok, detail = await tutoring_queue.confirm_access(target_room_id, event.sender)
            if not ok:
                await client.send_text(
                    room_id,
                    (
                        "⚠️ Te uniste a la cola, pero no fue posible confirmar automáticamente: "
                        f"{detail}. Te avisaremos apenas la sala quede libre."
                    ),
                )
                return
            # Notify student and ask teacher to confirm
            student_alias = _localpart(event.sender)
            await client.send_text(
                room_id,
                (
                    f"✅ Confirmación registrada para {room_label}. "
                    "El profesor recibirá un aviso para aprobar tu acceso."
                ),
            )
            await client.send_text(
                target_room_id,
                (
                    f"📣 {teacher_local} - {event.sender} solicita una tutoría.\n"
                    f"Por favor, responde con `!tutoria confirmar` para enviarle la invitación."
                ),
            )
            return

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
        sender_is_teacher = event.sender == teacher_mxid

        if sender_is_teacher:
            ok, detail, student_mxid, student_notify_room = await tutoring_queue.teacher_acknowledge(target_room_id, event.sender)
            if ok and student_mxid:
                invite_error = None
                try:
                    await client.invite_user(target_room_id, student_mxid)
                except Exception as exc:
                    invite_error = str(exc)
                student_alias = _localpart(student_mxid)
                await client.send_text(
                    room_id,
                    (
                        f"📨 Invitación enviada a {student_alias}."
                        + (f"\n⚠️ No se pudo enviar la invitación automática: {invite_error}" if invite_error else "")
                    ),
                )
                # Send notification to the room where the student originally confirmed
                notify_target = student_notify_room or student_mxid
                await client.send_text(
                    notify_target,
                    (
                        f"👨‍🏫 {student_alias}, el profesor {teacher_local} te ha invitado a la sala de tutoría. "
                        f"https://matrix.to/#/{target_room_id} "
                        "Por favor, únete cuando puedas."
                    ),
                )
            else:
                await client.send_text(room_id, f"❌ {detail}")
            return

        if tutoring_queue.is_teacher_ack_pending(target_room_id):
            await client.send_text(
                room_id,
                "⏳ Ya confirmaste tu turno. Espera a que el profesor te confirme.",
            )
            return

        ok, detail = await tutoring_queue.confirm_access(target_room_id, event.sender)
        if ok:
            student_alias = _localpart(event.sender)
            await client.send_text(
                room_id,
                "✅ Confirmación registrada. Espera la aprobación del profesor para recibir tu invitación.",
            )
            await client.send_text(
                target_room_id,
                (
                    f"📣 {teacher_local} - {event.sender} confirmó su turno en la cola.\n"
                    f"Por favor, responde con `!tutoria confirmar {teacher_local}` para enviarle la invitación."
                ),
            )
        else:
            await client.send_text(room_id, f"❌ {detail}")
        return

    if action == "acabar":
        sender_is_teacher = event.sender == teacher_mxid
        if not sender_is_teacher:
            is_active = await tutoring_queue.is_active_user(target_room_id, event.sender)
            if not is_active:
                await client.send_text(
                    room_id,
                    "❌ Solo el profesor o la persona atendida pueden acabar la tutoria.",
                )
                return
        ok, released_mxid, student_notify_room, transcript = await tutoring_queue.release_current(target_room_id)
        if ok:
            kick_note = ""
            if released_mxid:
                try:
                    await client.kick_user(
                        target_room_id,
                        released_mxid,
                        reason="Sala liberada via !tutoria acabar",
                    )
                except Exception as exc:
                    kick_note = f"\n⚠️ No se pudo expulsar automáticamente a {released_mxid}: {exc}"

                # Send transcript to the student
                if transcript and student_notify_room:
                    await tutoring_queue.send_transcript_file(
                        student_notify_room, transcript, teacher_local
                    )

            released_user = _localpart(released_mxid) if released_mxid else None
            tail = (
                f"Se notificará a la siguiente persona (sale {released_user})."
                if released_user
                else "Cola vacía por ahora."
            )
            await client.send_text(
                room_id,
                f"✅ Sala liberada. {tail}{kick_note}",
            )
        else:
            await client.send_text(room_id, f"❌ {released_mxid}")
        return

    if action == "salir":
        removed, detail = await tutoring_queue.leave_queue(target_room_id, event.sender)
        if removed:
            await client.send_text(
                room_id,
                f"✅ Saliste de la cola de {room_label}.",
            )
        else:
            await client.send_text(
                room_id,
                detail or "ℹ️ No estabas en la cola de esa sala.",
            )
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
