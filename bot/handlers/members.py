# handlers/members.py

import asyncio
from typing import Any, Optional
import requests

from config import MOODLE_URL, MOODLE_TOKEN, DB_TYPE
from core.db.constants import (
    COL_USER_MOODLE_ID,
    COL_ROOM_MOODLE_COURSE_ID,
    COL_ROOM_MOODLE_GROUP,
    get_db_modules,
)
from mautrix.types import EventType, Membership
from core.runtime_state import should_process_event
from core.tutoring_queue import tutoring_queue


MOODLE_TIMEOUT = 20
MOODLE_ENDPOINT = f"{MOODLE_URL.rstrip('/')}/webservice/rest/server.php"


def _payload_has_error(payload):
    return isinstance(payload, dict) and payload.get("exception")


async def _moodle_request(params, context: str) -> Optional[Any]:
    loop = asyncio.get_running_loop()

    def _do_request():
        response = requests.get(MOODLE_ENDPOINT, params=params, timeout=MOODLE_TIMEOUT)
        response.raise_for_status()
        return response.json() or []

    try:
        return await loop.run_in_executor(None, _do_request)
    except Exception as exc:
        print(f"[WARN] Error consultando Moodle ({context}): {exc}")
        return None


async def _is_user_enrolled_in_course(course_id: int, moodle_user_id: int) -> Optional[bool]:
    params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "core_enrol_get_enrolled_users",
        "moodlewsrestformat": "json",
        "courseid": course_id,
    }
    payload = await _moodle_request(params, "enrol_get_enrolled_users")
    if payload is None or _payload_has_error(payload):
        return None
    try:
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            try:
                if int(entry.get("id")) == moodle_user_id:
                    return True
            except (TypeError, ValueError):
                continue
    except Exception as exc:
        print(f"[WARN] No se pudo analizar la respuesta de Moodle (enrolled users): {exc}")
        return None
    return False


async def _is_user_in_group(group_id: int, moodle_user_id: int) -> Optional[bool]:
    params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "core_group_get_group_members",
        "moodlewsrestformat": "json",
        "groupids[0]": group_id,
    }
    payload = await _moodle_request(params, "group_get_group_members")
    if payload is None or _payload_has_error(payload):
        return None
    try:
        groups = payload if isinstance(payload, list) else []
        for group in groups:
            if not isinstance(group, dict):
                continue
            members = group.get("userids") or []
            for member in members:
                try:
                    if int(member) == moodle_user_id:
                        return True
                except (TypeError, ValueError):
                    continue
    except Exception as exc:
        print(f"[WARN] No se pudo analizar la respuesta de Moodle (group members): {exc}")
        return None
    return False


async def _resolve_group_identifier(course_id: int, stored_value: str) -> tuple[Optional[int], Optional[str]]:
    if stored_value in (None, ""):
        return None, None

    try:
        return int(stored_value), None
    except (TypeError, ValueError):
        pass

    params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "core_group_get_course_groups",
        "moodlewsrestformat": "json",
        "courseid": course_id,
    }
    payload = await _moodle_request(params, "group_get_course_groups")
    if payload is None or _payload_has_error(payload):
        return None, "no se pudieron obtener los grupos del curso"

    target = stored_value.strip().casefold()
    try:
        for group in payload:
            if not isinstance(group, dict):
                continue
            name = str(group.get("name", "")).strip().casefold()
            if name and name == target:
                try:
                    return int(group.get("id")), None
                except (TypeError, ValueError):
                    return None, f"el grupo {stored_value} no tiene un ID válido en Moodle"
    except Exception as exc:
        print(f"[WARN] No se pudo analizar la respuesta de Moodle (course groups): {exc}")
        return None, "no se pudieron analizar los grupos Moodle"

    return None, f"no existe el grupo '{stored_value}' en el curso"


async def _evaluate_knock_request(user_mxid: str, room_id: str) -> tuple[bool, Optional[str]]:
    db_queries = get_db_modules()[DB_TYPE]["queries"]

    user_row = await db_queries.get_user_by_matrix_id(user_mxid)
    if not user_row:
        return False, "usuario no registrado en la plataforma"

    room_row = await db_queries.get_room_by_matrix_id(room_id)
    if not room_row:
        return False, "sala no registrada en la base de datos"

    user = dict(user_row)
    room = dict(room_row)
    moodle_user_id = user.get(COL_USER_MOODLE_ID)

    if moodle_user_id in (None, ""):
        return False, "el usuario no tiene Moodle ID asociado"

    try:
        moodle_user_id = int(moodle_user_id)
    except (TypeError, ValueError):
        return False, "Moodle ID del usuario es inválido"

    course_id = room.get(COL_ROOM_MOODLE_COURSE_ID)
    try:
        course_id = int(course_id) if course_id is not None else None
    except (TypeError, ValueError):
        course_id = None

    if not course_id:
        return False, "la sala no tiene un curso Moodle asociado"

    enrolled = await _is_user_enrolled_in_course(course_id, moodle_user_id)
    if enrolled is None:
        return False, "no se pudo verificar la matrícula en Moodle"
    if not enrolled:
        return False, f"no está matriculado en el curso {course_id}"

    group_value = room.get(COL_ROOM_MOODLE_GROUP)
    if group_value not in (None, ""):
        group_id, group_err = await _resolve_group_identifier(course_id, str(group_value))
        if group_id is None:
            return False, group_err or "no se pudo determinar el grupo Moodle"

        in_group = await _is_user_in_group(group_id, moodle_user_id)
        if in_group is None:
            return False, "no se pudo verificar la pertenencia al grupo Moodle"
        if not in_group:
            return False, f"no pertenece al grupo Moodle '{group_value}'"

    return True, None

def register(client):
    async def on_member_event(event):
        if not should_process_event(event):
            return
        
        content = event.content
        membership = content.get("membership")

        room_id = event.room_id

        # Si el bot recibe una invitación
        if event.state_key == client.mxid and membership == Membership.INVITE:
            # Extraer el dominio del invitador y del bot
            inviter_domain = event.sender.split(':')[1] if ':' in event.sender else None
            bot_domain = client.mxid.split(':')[1] if ':' in client.mxid else None
            
            # Aceptar solo si el invitador es del mismo homeserver
            if inviter_domain and bot_domain and inviter_domain == bot_domain:
                try:
                    await client.join_room(room_id)
                    print(f"[+] Bot aceptó invitación a sala {room_id} de {event.sender}")
                except Exception as e:
                    print(f"[ERROR] No se pudo unir a la sala {room_id}: {e}")
            else:
                print(f"[WARN] Invitación rechazada de {event.sender} (homeserver diferente)")
            return

        # Ignora eventos del propio bot
        if event.state_key == client.mxid:
            return

        # Procesa solicitudes de acceso (knock)
        knock_value = getattr(Membership, "KNOCK", "knock")
        if membership == knock_value:
            allowed, denial_reason = await _evaluate_knock_request(event.state_key, room_id)
            if allowed:
                try:
                    await client.invite_user(room_id, event.state_key)
                    await client.send_text(
                        room_id,
                        f"✅ {event.state_key} ha sido invitado automáticamente tras verificar su matrícula.",
                    )
                    print(f"[INFO] Invitación automática enviada a {event.state_key} en {room_id}")
                except Exception as e:
                    print(f"[ERROR] No se pudo invitar a {event.state_key} en {room_id}: {e}")
            else:
                message = denial_reason or "el usuario no cumple los requisitos"
                try:
                    await client.send_text(
                        room_id,
                        f"⛔ Solicitud de acceso de {event.state_key} rechazada: {message}.",
                    )
                except Exception as e:
                    print(f"[WARN] No se pudo notificar el rechazo en {room_id}: {e}")
            return

        # Detecta unirse a la sala
        if membership == Membership.JOIN:
            await client.send_text(
                room_id,
                f"🎓 ¡Bienvenido/a {event.state_key} a la sala!"
            )

        # Detecta abandonar la sala
        elif membership == Membership.LEAVE:
                # Verifica si la sala es de tutoría para liberar la cola
            try:
                db_queries = get_db_modules()[DB_TYPE]["queries"]
                room_row = await db_queries.get_room_by_matrix_id(room_id)
            except Exception:
                room_row = None
            if room_row:
                room_data = dict(room_row)
                if room_data.get(COL_ROOM_MOODLE_COURSE_ID) in (None, ""):
                    released, notify_room, transcript = await tutoring_queue.handle_room_leave(room_id, event.state_key)
                    if released:
                        print(f"[INFO] Cola de tutoría liberada automáticamente en {room_id}")
                        # Send transcript to the student if available
                        if transcript and notify_room:
                            await tutoring_queue.send_transcript_file(notify_room, transcript)

        # Detecta invitación a otros usuarios
        elif membership == Membership.INVITE:
            await client.send_text(
                room_id,
                f"📩 {event.sender} ha invitado a {event.state_key}."
            )
    
    client.add_event_handler(EventType.ROOM_MEMBER, on_member_event)
