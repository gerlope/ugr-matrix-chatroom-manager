# handlers/messages.py

from mautrix.types import EventType, MessageType
from core.command_registry import execute_command
from core.runtime_state import should_process_event
from core.tutoring_queue import tutoring_queue

def register(client):
    async def on_message(event):
        # Ignore messages from the bot itself
        if event.sender == client.mxid:
            return

        if not should_process_event(event):
            return
        
        # Check if event has content and it's a text message
        if not hasattr(event, "content") or not event.content:
            return
        
        # Only process text messages
        msgtype = event.content.get("msgtype")
        if msgtype != MessageType.TEXT:
            return
        
        body = event.content.get("body", "").strip()
        if not body:
            return
        
        # Record message if this room has an active tutoring session
        if tutoring_queue.is_recording(event.room_id):
            tutoring_queue.record_message(event.room_id, event.sender, body)
        
        print(f"[Mensaje] {event.sender}: {body}")
        await execute_command(client, event.room_id, event, body)
    
    client.add_event_handler(EventType.ROOM_MESSAGE, on_message)
