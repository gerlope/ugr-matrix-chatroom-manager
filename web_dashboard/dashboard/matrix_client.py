from datetime import datetime
from typing import List, Optional
import asyncio
import logging
import threading
import concurrent.futures
from typing import Any

from asgiref.sync import async_to_sync

from mautrix.client import Client
from mautrix.types import Membership

from config import HOMESERVER, SERVER_NAME, USERNAME, PASSWORD

logger = logging.getLogger(__name__)

# Single global mautrix client
_CLIENT: Optional[Client] = None
_client_lock = asyncio.Lock()

# Background thread / loop owned client. The client must be used only on the
# background event loop. We'll expose helpers that schedule work there.
_bg_loop: Optional[asyncio.AbstractEventLoop] = None
_bg_thread: Optional[threading.Thread] = None
_bg_started = threading.Event()
_bg_lock = threading.Lock()
_bg_client: Optional[Client] = None


async def get_client() -> Client:
    """Obtener el Client global; lo crea y loguea con USERNAME/PASSWORD si hace falta."""
    global _CLIENT
    async with _client_lock:
        if _CLIENT is not None:
            # If the client's underlying aiohttp session or its event loop is closed,
            # recreate the client so subsequent requests open a new session on the
            # currently running event loop. This avoids "Event loop is closed" errors
            # when `async_to_sync` creates a temporary loop.
            session = None
            try:
                api = getattr(_CLIENT, "api", None)
                session = getattr(api, "session", None)
            except Exception:
                session = None

            session_usable = True
            if session is None:
                session_usable = False
            else:
                try:
                    if getattr(session, "closed", False):
                        session_usable = False
                    else:
                        loop = getattr(session, "loop", None)
                        if loop is not None and getattr(loop, "is_closed", lambda: False)():
                            session_usable = False
                except Exception:
                    session_usable = False

            if session_usable:
                return _CLIENT

            # Try to close old session if possible, then drop the client so we recreate it.
            try:
                if session is not None and not getattr(session, "closed", False):
                    await session.close()
            except Exception:
                pass
            _CLIENT = None

        # Crear cliente; se pasa BOT_MXID si está disponible
        client = Client(mxid=USERNAME, base_url=HOMESERVER)
        # Login con contraseña — pass as keyword to match mautrix API
        await client.login(password=PASSWORD)
        _CLIENT = client
        return _CLIENT


def _bg_thread_main() -> None:
    """Thread target: create and run the background asyncio loop."""
    global _bg_loop
    loop = asyncio.new_event_loop()
    _bg_loop = loop
    asyncio.set_event_loop(loop)
    _bg_started.set()
    try:
        loop.run_forever()
    finally:
        # Clean shutdown
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


def _ensure_bg_loop() -> asyncio.AbstractEventLoop:
    """Ensure the background thread and loop are running; return the loop."""
    global _bg_thread, _bg_loop
    if _bg_loop is not None and _bg_loop.is_running():
        return _bg_loop
    with _bg_lock:
        if _bg_loop is not None and _bg_loop.is_running():
            return _bg_loop
        _bg_started.clear()
        t = threading.Thread(target=_bg_thread_main, daemon=True)
        t.start()
        # Wait for loop to be created by the thread
        _bg_started.wait(timeout=5.0)
        _bg_thread = t
        if _bg_loop is None:
            raise RuntimeError("Failed to start background event loop")
        return _bg_loop


def _run_on_bg(coro: Any) -> concurrent.futures.Future:
    """Schedule a coroutine to run on the background loop; return a concurrent.futures.Future."""
    loop = _ensure_bg_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop)


async def _await_future_in_async(fut: concurrent.futures.Future):
    """Await a concurrent.futures.Future from within an async function."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fut.result)

async def create_room(
    name: str = "",
    topic: Optional[str] = None,
    general_room_id: Optional[str] = None,
    join_rule: Optional[str] = None,
    allowed_room_ids: Optional[List[str]] = None,
) -> str:
    # Run actual creation on the background loop so the mautrix Client runs
    # on a single dedicated event loop.
    async def _bg():
        # create power levels and initial state
        power_levels = {
            "users": {USERNAME: 100} if USERNAME else {},
            "invite": 50,
            "events_default": 0,
            "state_default": 50,
            "users_default": 0,
        }
        # Default to knock when tied to a general room, otherwise invite-only unless caller overrides
        join_rule_value = join_rule or ("knock" if general_room_id else "invite")
        allowed = [rid for rid in (allowed_room_ids or []) if rid]
        if join_rule_value.endswith("restricted") and not allowed and general_room_id:
            allowed = [general_room_id]
        join_rule_content: dict[str, Any] = {"join_rule": join_rule_value}
        if allowed:
            # MSC3787 join rules expect allow entries referencing membership in other rooms
            unique_allowed = list(dict.fromkeys(allowed))
            join_rule_content["allow"] = [
                {"type": "m.room_membership", "room_id": rid} for rid in unique_allowed
            ]
        
        initial_state = [
            {"type": "m.room.power_levels", "state_key": "", "content": power_levels},
        ]
        # ensure client exists on bg loop
        bg_client = await _bg_get_client()
        # Create room - the bot creating it will auto-join as creator
        # Use room_version 10 to support knock and knock_restricted join rules
        # Don't use preset to avoid it overriding our join rules
        resp = await bg_client.create_room(
            name=name,
            topic=topic or name,
            initial_state=initial_state,
            room_version="10",
            is_direct=False,
        )
        room_id = resp if isinstance(resp, str) else getattr(resp, "room_id", None)
        if not room_id:
            logger.error("Failed to get room_id from create_room response")
            raise RuntimeError("Room creation did not return a room_id")
        logger.info(f"Created room {room_id} with bot {USERNAME}")
        
        # Set join rules after creation to ensure they're not overridden
        try:
            await bg_client.send_state_event(
                room_id=room_id,
                event_type="m.room.join_rules",
                state_key="",
                content=join_rule_content,
            )
            logger.info(f"Set join rules to {join_rule_content['join_rule']} for room {room_id}")
        except Exception as e:
            logger.error(f"Failed to set join rules for room {room_id}: {e}")
        
        # Give the server a moment to fully process the join
        import asyncio
        await asyncio.sleep(0.5)
        
        return room_id

    fut = _run_on_bg(_bg())
    # From an async context, await using helper; callers often call this via async_to_sync
    return await _await_future_in_async(fut)

async def join_user_admin(room_id: str, user_id: str) -> None:
    """Invite a user to the room using the client API (replaces admin/join HTTP endpoint)."""
    async def _bg():
        bg_client = await _bg_get_client()
        try:
            await bg_client.invite_user(room_id, user_id)
        except Exception as e:
            error_msg = str(e)
            # Ignore if user is already in the room
            if "already in the room" in error_msg:
                logger.debug(f"{user_id} already in room {room_id}")
                return
            raise

    fut = _run_on_bg(_bg())
    return await _await_future_in_async(fut)

async def get_members(room_id: str) -> List[str]:
    async def _bg():
        bg_client = await _bg_get_client()
        state_events = await bg_client.get_state(room_id)
        members: List[str] = []
        for ev in state_events:
            try:
                if str(ev.type) == "m.room.member" and ev.content.get("membership") == Membership.JOIN:
                    members.append(ev.state_key)
            except Exception:
                continue
        return members

    fut = _run_on_bg(_bg())
    return await _await_future_in_async(fut)

async def get_room_name(room_id: str) -> Optional[str]:
    async def _bg():
        bg_client = await _bg_get_client()
        try:
            content = await bg_client.get_state_event(room_id, "m.room.name", "")
            return content.get("name")
        except Exception:
            return None

    fut = _run_on_bg(_bg())
    return await _await_future_in_async(fut)

async def set_room_name(room_id: str, name: str) -> None:
    async def _bg():
        bg_client = await _bg_get_client()
        await bg_client.send_state_event(room_id, "m.room.name", {"name": name})

    fut = _run_on_bg(_bg())
    return await _await_future_in_async(fut)

def academic_closed_prefix(created_at: datetime) -> str:
    year = created_at.year
    month = created_at.month
    start_year = year if month >= 9 else year - 1
    xx = start_year % 100
    yy = (start_year + 1) % 100
    return f"({xx:02d}/{yy:02d} CLOSED) "

async def ensure_room_name_prefixed(room_id: str, prefix: str) -> None:
    try:
        current = await get_room_name(room_id)
        if current is None:
            new_name = prefix.strip()
        elif current.startswith(prefix):
            return
        else:
            new_name = prefix + current
        await set_room_name(room_id, new_name)
    except Exception:
        pass

async def set_user_power_level(room_id: str, user_id: str, level: int) -> None:
    async def _bg():
        bg_client = await _bg_get_client()
        try:
            power = await bg_client.get_state_event(room_id, "m.room.power_levels", "")
        except Exception:
            power = {}
        users_pl = power.get("users", {})
        users_pl[user_id] = level
        power["users"] = users_pl
        await bg_client.send_state_event(room_id, "m.room.power_levels", power)

    fut = _run_on_bg(_bg())
    return await _await_future_in_async(fut)

async def silence_room_members(room_id: str, bot_mxid: Optional[str] = USERNAME) -> int:
    members = await get_members(room_id)
    affected = 0
    for mxid in members:
        if bot_mxid and mxid == bot_mxid:
            continue
        try:
            await set_user_power_level(room_id, mxid, -10)
            affected += 1
        except Exception:
            pass
    return affected


async def get_invited_members(room_id: str) -> List[str]:
    """Get list of users with 'invite' membership (pending invites)."""
    async def _bg():
        bg_client = await _bg_get_client()
        state_events = await bg_client.get_state(room_id)
        invited: List[str] = []
        for ev in state_events:
            try:
                if str(ev.type) == "m.room.member" and ev.content.get("membership") == Membership.INVITE:
                    invited.append(ev.state_key)
            except Exception:
                continue
        return invited

    fut = _run_on_bg(_bg())
    return await _await_future_in_async(fut)


async def kick_user(room_id: str, user_id: str, reason: str = "Removed from room") -> bool:
    """Kick a user from the room (also cancels pending invites)."""
    async def _bg():
        bg_client = await _bg_get_client()
        try:
            await bg_client.kick_user(room_id, user_id, reason)
            return True
        except Exception as e:
            error_msg = str(e)
            # 403/404 means user not in room or already left
            if "403" in error_msg or "404" in error_msg:
                return False
            raise

    fut = _run_on_bg(_bg())
    return await _await_future_in_async(fut)


async def cancel_pending_invites(room_id: str, bot_mxid: Optional[str] = USERNAME) -> int:
    """Cancel all pending invites in the room by kicking invited users."""
    invited = await get_invited_members(room_id)
    cancelled = 0
    for mxid in invited:
        if bot_mxid and mxid == bot_mxid:
            continue
        try:
            ok = await kick_user(room_id, mxid, "Room closed, invite cancelled")
            if ok:
                cancelled += 1
        except Exception:
            pass
    return cancelled

async def get_room_topic(room_id: str) -> str:
    async def _bg():
        bg_client = await _bg_get_client()
        try:
            content = await bg_client.get_state_event(room_id, "m.room.topic", "")
            return content.get("topic") or ""
        except Exception:
            return ""

    fut = _run_on_bg(_bg())
    return await _await_future_in_async(fut)

async def set_room_topic(room_id: str, topic: str):
    async def _bg():
        bg_client = await _bg_get_client()
        await bg_client.send_state_event(room_id, "m.room.topic", {"topic": topic})

    fut = _run_on_bg(_bg())
    return await _await_future_in_async(fut)

def build_invite_link(room_id: str) -> str:
    return f"https://matrix.to/#/{room_id}"

async def append_subgroup_link_to_topic(
    general_room_id: str,
    subgroup_room_id: str,
    shortcode: str,
) -> None:
    current = await get_room_topic(general_room_id)
    link = build_invite_link(subgroup_room_id)
    line = f"Subgrupo {shortcode}: {link}"
    if line in current:
        return
    new_topic = (current + "\n" + line).strip() if current else line
    await set_room_topic(general_room_id, new_topic)

async def remove_subgroup_link_from_topic(
    general_room_id: str,
    subgroup_room_id: str,
    shortcode: str,
) -> None:
    current = await get_room_topic(general_room_id)
    if not current:
        return
    link = build_invite_link(subgroup_room_id)
    line = f"Subgrupo {shortcode}: {link}"
    lines = [l for l in current.splitlines() if l.strip() and l.strip() != line]
    new_topic = "\n".join(lines)
    if new_topic != current:
        await set_room_topic(general_room_id, new_topic)

async def invite_all_members(room_id: str, matrix_ids: List[str]) -> None:
    if not matrix_ids:
        return
    async def _bg():
        bg_client = await _bg_get_client()
        logger.info(f"Inviting {len(matrix_ids)} users to room {room_id}")
        
        # First verify the bot is actually in the room
        try:
            members = await bg_client.get_state(room_id)
            bot_in_room = any(
                str(ev.type) == "m.room.member" 
                and ev.state_key == USERNAME 
                and ev.content.get("membership") == Membership.JOIN
                for ev in members
            )
            if not bot_in_room:
                logger.error(f"Bot {USERNAME} is not a member of room {room_id}, cannot invite users")
                return
            logger.debug(f"Verified bot {USERNAME} is in room {room_id}")
        except Exception as e:
            logger.warning(f"Could not verify bot membership in {room_id}: {e}, proceeding anyway")
        
        for mxid in matrix_ids:
            try:
                logger.debug(f"Inviting {mxid} to {room_id}")
                await bg_client.invite_user(room_id, mxid)
            except Exception as e:
                logger.warning(f"Failed to invite {mxid} to {room_id}: {e}")
                # Continue inviting others even if one fails
                continue

    fut = _run_on_bg(_bg())
    return await _await_future_in_async(fut)

async def get_power_levels(room_id: str) -> dict:
    async def _bg():
        bg_client = await _bg_get_client()
        try:
            content = await bg_client.get_state_event(room_id, "m.room.power_levels", "")
            return content or {}
        except Exception:
            return {}

    fut = _run_on_bg(_bg())
    return await _await_future_in_async(fut)


def fetch_matrix_room_members(room_id: str) -> List[str]:
    """Synchronous wrapper to fetch current joined members for a room.

    Some dashboard code expects a synchronous helper; expose a thin wrapper
    that calls the async `get_members` implementation via `async_to_sync`.
    """
    try:
        return async_to_sync(get_members)(room_id)
    except Exception:
        logger.exception("Error fetching Matrix members for room %s", room_id)
        return []


async def _bg_get_client() -> Client:
    """Get or create the mautrix Client on the background event loop.

    This function runs on the background loop and stores the client in
    `_bg_client` so subsequent scheduled work reuses the same client/session.
    """
    global _bg_client
    if _bg_client is not None:
        return _bg_client
    # Create and login the client on the bg loop
    client = Client(mxid=USERNAME, base_url=HOMESERVER)
    login_resp = await client.login(password=PASSWORD)
    logger.info(f"Background client logged in as {USERNAME}, device_id: {login_resp.device_id}")
    _bg_client = client
    return _bg_client


def close_background_client(timeout: float = 5.0) -> None:
    """Synchronously close the background client and stop the bg loop.

    Call this at process exit to avoid unclosed aiohttp session warnings.
    """
    global _bg_client, _bg_loop, _bg_thread
    if _bg_loop is None:
        return
    # Schedule client close
    try:
        fut = asyncio.run_coroutine_threadsafe(_bg_client.api.session.close(), _bg_loop) if _bg_client and getattr(_bg_client, "api", None) else None
        if fut:
            fut.result(timeout=timeout)
    except Exception:
        pass
    # stop the loop
    try:
        _bg_loop.call_soon_threadsafe(_bg_loop.stop)
    except Exception:
        pass
    # join the thread
    try:
        if _bg_thread is not None:
            _bg_thread.join(timeout=timeout)
    except Exception:
        pass
