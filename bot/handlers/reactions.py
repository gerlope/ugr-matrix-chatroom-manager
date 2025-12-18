# handlers/reactions.py

from mautrix.types import EventType
from mautrix.errors.request import MNotFound
import logging
from core.db.constants import COL_ROOM_ID, COL_USER_IS_TEACHER
from core.db.constants import get_db_modules
from core.runtime_state import should_process_event
from config import DB_TYPE

def register(client):
    async def on_add_reaction(event):
        """Handler para agregar o incrementar reacciones."""
        
        # Ignore messages from the bot itself
        if event.sender == client.mxid:
            return

        if not should_process_event(event):
            return
        
        relates_to = event.content.get("_relates_to", {})
        emoji = relates_to.get("key", "❓")
        reacted_to_event_id = relates_to.get("event_id")
        sender_mxid = event.sender
        room_id = event.room_id

        db = get_db_modules()[DB_TYPE]["queries"]

        # Verificar profesor
        teacher = await db.get_user_by_matrix_id(sender_mxid)
        if not teacher or not teacher[COL_USER_IS_TEACHER]:
            return

        # If the reaction does not reference an event_id, ignore it
        if not reacted_to_event_id:
            logger = logging.getLogger(__name__)
            logger.warning("Reaction event missing target event_id: reaction_event=%s room=%s sender=%s", getattr(event, 'event_id', None), room_id, sender_mxid)
            return

        # Obtener estudiante
        try:
            reacted_event = await client.get_event(room_id, reacted_to_event_id)
        except MNotFound:
            logger = logging.getLogger(__name__)
            logger.warning("Reacted-to event not found: %s in %s", reacted_to_event_id, room_id)
            return
        except Exception:
            logger = logging.getLogger(__name__)
            logger.exception("Failed fetching reacted event %s in room %s", reacted_to_event_id, room_id)
            return
        if not reacted_event:
            return
        student_mxid = reacted_event.sender
        student = await db.get_user_by_matrix_id(student_mxid)
        if not student:
            return

        # Obtener moodle_course_id
        room_data = await db.get_room_by_matrix_id(room_id)
        if not room_data:
            return
        room_id = room_data[COL_ROOM_ID]

        # Agregar o incrementar reacción
        await db.add_or_increase_reaccion(
            teacher_id=teacher["id"],
            student_id=student["id"],
            room_id=room_id,
            reaction_type=emoji,
            increment=1
        )
    
    client.add_event_handler(EventType.REACTION, on_add_reaction)


async def redact_reaction(event, client):
    """Handler para redactar reacciones."""
    relates_to = event.content.get("_relates_to", {})
    print(event)
    emoji = relates_to.get("key", "❓")
    reacted_to_event_id = relates_to.get("event_id")
    sender_mxid = event.sender
    room_id = event.room_id

    db = get_db_modules()[DB_TYPE]["queries"]

    if sender_mxid == client.mxid:
        return

    if not should_process_event(event):
        return

    # Verificar profesor
    teacher = await db.get_user_by_matrix_id(sender_mxid)
    if not teacher or not teacher[COL_USER_IS_TEACHER]:
        return

    # If the reaction does not reference an event_id, ignore it
    if not reacted_to_event_id:
        logger = logging.getLogger(__name__)
        logger.warning("Redacted-reaction missing target event_id: reaction_event=%s room=%s sender=%s", getattr(event, 'event_id', None), room_id, sender_mxid)
        return

    # Obtener estudiante
    try:
        reacted_event = await client.get_event(room_id, reacted_to_event_id)
    except MNotFound:
        logger = logging.getLogger(__name__)
        logger.warning("Reacted-to event not found (on redact): %s in %s", reacted_to_event_id, room_id)
        return
    except Exception:
        logger = logging.getLogger(__name__)
        logger.exception("Failed fetching reacted event %s in room %s (on redact)", reacted_to_event_id, room_id)
        return
    if not reacted_event:
        return
    student_mxid = reacted_event.sender
    student = await db.get_user_by_matrix_id(student_mxid)
    if not student:
        return

    # Obtener moodle_course_id
    room_data = await db.get_room_by_matrix_id(room_id)
    if not room_data:
        return
    room_id = room_data[COL_ROOM_ID]

    # Disminuir o eliminar reacción
    await db.decrease_or_delete_reaccion(
        teacher_id=teacher["id"],
        student_id=student["id"],
        room_id=room_id,
        reaction_type=emoji,
        decrement=1
    )
