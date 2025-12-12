# handlers/redactions.py

from mautrix.types import EventType
from handlers.reactions import redact_reaction
from core.runtime_state import should_process_event


def register(client):
    async def handle_redaction(event):
        """
        Handles a redaction event.
        If the redacted event was a reaction, calls redact_reaction.
        """
        redacted_event_id = event.redacts  # The event being redacted
        sender_mxid = event.sender
        room_id = event.room_id

        # You may want to ignore bot's own redactions
        if sender_mxid == client.mxid:
            return
        
        if not should_process_event(event):
            return

        # Fetch the redacted event to check its type
        try:
            redacted_event = await client.get_event(room_id, redacted_event_id)
        except Exception:
            return  # Event might not exist anymore

        if redacted_event and redacted_event.type == EventType.REACTION:
            await redact_reaction(redacted_event, client)
    
    client.add_event_handler(EventType.ROOM_REDACTION, handle_redaction)
