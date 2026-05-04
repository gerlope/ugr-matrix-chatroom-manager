# handlers/reactions.py

from datetime import datetime, timezone
import logging

from mautrix.types import EventType
from mautrix.errors.request import MNotFound
from core.db.constants import COL_ROOM_ID, COL_USER_IS_TEACHER
from core.db.modules import DB_MODULES
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
        reaction_event_id = event.event_id
        sender_mxid = event.sender
        room_id = event.room_id

        db = DB_MODULES[DB_TYPE]["queries"]

        # Verificar profesor
        teacher = await db.get_user_by_matrix_id(sender_mxid)
        if not teacher or not teacher[COL_USER_IS_TEACHER]:
            return

        # If the reaction does not reference an event_id, ignore it
        if not reacted_to_event_id:
            logger = logging.getLogger(__name__)
            logger.warning("Reaction event missing target event_id: reaction_event=%s room=%s sender=%s", getattr(event, 'event_id', None), room_id, sender_mxid)
            return
        if not reaction_event_id:
            logger = logging.getLogger(__name__)
            logger.warning("Reaction event missing its own event_id: room=%s sender=%s", room_id, sender_mxid)
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

        message = ""
        if hasattr(reacted_event, "content") and reacted_event.content:
            message = reacted_event.content.get("body", "") or ""

        # Obtener moodle_course_id
        room_data = await db.get_room_by_matrix_id(room_id)
        if not room_data:
            return
        room_db_id = room_data[COL_ROOM_ID]

        event_timestamp = getattr(event, "timestamp", None)
        reaction_date = (
            datetime.fromtimestamp(event_timestamp / 1000, tz=timezone.utc)
            if event_timestamp
            else datetime.now(timezone.utc)
        )

        # Guardar reacción individual
        await db.add_reaccion(
            teacher_id=teacher["id"],
            student_id=student["id"],
            room_id=room_db_id,
            event_id=reaction_event_id,
            reaction_type=emoji,
            message=message,
            reaction_date=reaction_date,
        )
    
    client.add_event_handler(EventType.REACTION, on_add_reaction)


async def redact_reaction(event):
    """Handler para redactar reacciones."""
    sender_mxid = event.sender
    room_id = event.room_id
    reaction_event_id = getattr(event, "event_id", None)

    db = DB_MODULES[DB_TYPE]["queries"]

    # Verificar profesor
    teacher = await db.get_user_by_matrix_id(sender_mxid)
    if not teacher or not teacher[COL_USER_IS_TEACHER]:
        return

    if not reaction_event_id:
        logger = logging.getLogger(__name__)
        logger.warning("Redacted-reaction missing event_id: room=%s sender=%s", room_id, sender_mxid)
        return

    # Eliminar la reacción individual almacenada para ese evento
    await db.delete_reaccion(reaction_event_id)
