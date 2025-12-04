# core/command_registry.py

import importlib
import pkgutil
import commands
from config import COMMAND_PREFIX

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

    if cmd in COMMANDS:
        try:
            await COMMANDS[cmd]["module"].run(client, room_id, event, args)
        except Exception as e:
            await client.send_text(room_id, f"⚠️ Error ejecutando comando `{cmd}`: {e}")
    else:
        await client.send_text(room_id, f"❌ Comando desconocido: {cmd}")
