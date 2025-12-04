# handlers/members.py

from mautrix.types import EventType, Membership
from datetime import datetime, timezone

# Track when the bot started to ignore old events
bot_start_time = None

def register(client):
    global bot_start_time
    bot_start_time = datetime.now(timezone.utc)
    
    async def on_member_event(event):
        # Ignore events that happened before the bot started
        if hasattr(event, 'timestamp') and event.timestamp:
            event_time = datetime.fromtimestamp(event.timestamp / 1000, tz=timezone.utc)
            if event_time < bot_start_time:
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

        # Detecta unirse a la sala
        if membership == Membership.JOIN:
            await client.send_text(
                room_id,
                f"🎓 ¡Bienvenido/a {event.state_key} a la sala!"
            )

        # Detecta abandonar la sala
        elif membership == Membership.LEAVE:
            await client.send_text(
                room_id,
                f"👋 {event.state_key} ha salido de la sala."
            )

        # Detecta invitación a otros usuarios
        elif membership == Membership.INVITE:
            await client.send_text(
                room_id,
                f"📩 {event.sender} ha invitado a {event.state_key}."
            )
    
    client.add_event_handler(EventType.ROOM_MEMBER, on_member_event)
