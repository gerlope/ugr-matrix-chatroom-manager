# core/command_registry.py

import importlib
import pkgutil
import commands
from config import COMMAND_PREFIX, DB_TYPE
from core.db.constants import get_db_modules

COMMANDS = {}

def load_commands():
    """Carga dinámicamente los comandos desde el paquete `commands`."""
    for _, module_name, _ in pkgutil.iter_modules(commands.__path__):
        try:
            module = importlib.import_module(f"commands.{module_name}")

            # Verificar que tenga un método 'run'
            if hasattr(module, "run") and callable(module.run):
                usage = getattr(module, "USAGE", f"!{module_name}")
                description = getattr(module, "DESCRIPTION", "Sin descripción disponible.")

                COMMANDS[module_name] = {
                    "module": module,
                    "usage": usage,
                    "description": description,
                }
            else:
                print(f"[!] El módulo {module_name} no tiene un 'run' válido, se ignora.")

        except Exception as e:
            print(f"[!] Error cargando módulo {module_name}: {e}")

    print(f"[+] {len(COMMANDS)} comandos cargados: {list(COMMANDS.keys())}")

async def execute_command(client, room_id, event, body):
    if not body.startswith(COMMAND_PREFIX):
        return

    parts = body[len(COMMAND_PREFIX):].strip().split()
    if not parts:
        await client.send_text(room_id, "⚠️ No has introducido ningún comando.")
        return
    
    cmd = parts[0]
    args = parts[1:]

    # ────────────────────────────────────────────────────────────────────────────────
    # Room-type check: only allow commands in DM rooms or tutoring rooms.
    # ────────────────────────────────────────────────────────────────────────────────
    db = get_db_modules()[DB_TYPE]["queries"]

    # Check if this is a tutoring room (no course, but teacher room in DB)
    is_tutoring = await db.is_tutoring_room(room_id)

    # Check if this is a DM (direct message) room by checking if it is a direct room state event
    is_dm = False
    try:
        # A room is a DM if there are only 2 joined members (bot + user).
        # Alternatively, we check for the room being marked as a direct room, but
        # the simplest robust approach is to count joined members.
        members_state = await client.get_joined_members(room_id)
        if members_state and len(members_state) <= 2:
            is_dm = True
    except Exception:
        pass

    if not is_dm and not is_tutoring:
        # Send warning message
        await client.send_text(
            room_id,
            f"⚠️ {event.sender.split(':')[0][1:]}, los comandos solo están disponibles en mensajes directos con el bot o en salas de tutoría."
        )
        # If the command is `responder`, also redact the user's message
        if cmd == "responder":
            try:
                await client.redact(room_id, event.event_id, reason="Ocultación de tu respuesta.")
            except Exception:
                pass
        return

    if cmd in COMMANDS:
        try:
            await COMMANDS[cmd]["module"].run(client, room_id, event, args)
        except Exception as e:
            await client.send_text(room_id, f"⚠️ Error ejecutando comando `{cmd}`: {e}")
    else:
        await client.send_text(room_id, f"❌ Comando desconocido: {cmd}")
