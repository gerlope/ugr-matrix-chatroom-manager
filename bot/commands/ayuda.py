# commands/ayuda.py

USAGE = "!ayuda"
DESCRIPTION = "Muestra esta lista de comandos disponibles."

from core.command_registry import COMMANDS

async def run(client, room_id, event, args):
    lines = []
    for name, info in sorted(COMMANDS.items()):
        usage = info["usage"]
        desc = info["description"]
        lines.append(f"• {usage} — {desc}")

    help_text = "\n".join(lines)

    await client.send_text(
        room_id,
        f"📘 Comandos disponibles:\n\n{help_text}\n\nUsa !<comando> para ejecutarlos."
    )
