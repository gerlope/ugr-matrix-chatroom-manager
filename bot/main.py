# main.py

import asyncio

from core.client_manager import create_client
from core.command_registry import load_commands
from core.event_router import register_event_handlers
from core.db.modules import DB_MODULES
from core.runtime_state import set_bot_start_time
from core.tutoring_queue import tutoring_queue
from core.question_notifier import question_notifier

from config_bot import DB_TYPE

async def main():
    db_conn = DB_MODULES[DB_TYPE]["conn"]
    await db_conn.connect()
    client = await create_client()
    tutoring_queue.configure_client(client)
    question_notifier.configure_client(client)
    load_commands()
    register_event_handlers(client)

    print("[*] Bot iniciado — escuchando mensajes...")
    try:
        from mautrix.types import Filter, RoomFilter, RoomEventFilter
        
        # Create a filter that includes all room messages
        sync_filter = Filter(
            room=RoomFilter(
                timeline=RoomEventFilter(
                    types=["m.room.message", "m.room.member", "m.reaction", "m.room.redaction"]
                )
            )
        )
        
        # Perform an initial sync to get current state, then start listening for new events
        await client.sync(timeout=0, full_state=False, set_presence="online")
        set_bot_start_time()
        print("[+] Sincronización inicial completada, procesando solo eventos nuevos")
        
        # Start the question notifier background task
        question_notifier.start()
        
        await client.start(filter_data=sync_filter)
    except KeyboardInterrupt:
        print("[*] Bot detenido por usuario")
    finally:
        question_notifier.stop()
        try:
            await client.stop()
        except Exception:
            pass
        try:
            await client.close()
        except Exception:
            pass
        await db_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
