#!/usr/bin/env python3
"""
Sincroniza usuarios y asignaturas de Moodle con Matrix y PostgreSQL.

- Crea usuarios en Matrix si no existen.
- Inserta usuarios en la tabla PostgreSQL `users` con su moodle_id y si son profesores.
- Crea una sala Matrix por cada asignatura Moodle y otra para profesores.
- Desactiva salas antiguas en la base de datos.
- Une automáticamente a los usuarios a las salas usando la Admin API.
"""

import asyncio
from datetime import datetime
from pathlib import Path
import aiohttp
import asyncpg
import requests
import string
import secrets
from config import (MOODLE_URL, MOODLE_TOKEN,
                    HOMESERVER, SERVER_NAME, USERNAME, PASSWORD, MATRIX_ADMIN_TOKEN,
                    DB_USER, DB_PASSWORD, DB_NAME, DB_HOST, DB_PORT
                    )

# ==============================
# CONFIGURACIÓN
# ==============================
# --- PostgreSQL ---
PG_DSN = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
# --- Parámetros generales ---
ROOM_VISIBILITY = "private"
DRY_RUN = False  # True = modo simulación
DEACTIVATE_ALL_ROOMS = True  # Si True, desactiva todas las salas y expulsa a todos sus miembros al inicio

# ==============================
# UTILIDADES
# ==============================

def gen_password(length: int = 12):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def safe_localpart(email: str, fallback: str):
    if not email:
        candidate = fallback
    else:
        candidate = email.split('@')[0]
    allowed = [ch for ch in candidate if ch.isalnum() or ch in "._-"]
    s = ''.join(allowed).lower().strip('._-')
    return s[:64] if s else fallback

def matrix_user_id_from_email(email: str, SERVER_NAME: str):
    local = safe_localpart(email, "user")
    return f"@{local}:{SERVER_NAME}"

def normalize_mxid(user: str, server: str) -> str:
    """Return a proper MXID from either a localpart or a full '@user:server'."""
    if user.startswith("@") and ":" in user:
        return user
    if user.startswith("@") and ":" not in user:
        return f"{user}:{server}"
    # Plain localpart
    return f"@{user}:{server}"

# Normalize bot MXID once for consistent comparisons
BOT_MXID = normalize_mxid(USERNAME, SERVER_NAME)

# ==============================
# FUNCIONES MOODLE
# ==============================

def get_courses():
    endpoint = f"{MOODLE_URL}/webservice/rest/server.php"
    params = {
        'wstoken': MOODLE_TOKEN,
        'wsfunction': 'core_course_get_courses',
        'moodlewsrestformat': 'json'
    }
    resp = requests.get(endpoint, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []

def get_course_users(course_id):
    endpoint = f"{MOODLE_URL}/webservice/rest/server.php"
    params = {
        'wstoken': MOODLE_TOKEN,
        'wsfunction': 'core_enrol_get_enrolled_users',
        'moodlewsrestformat': 'json',
        'courseid': course_id
    }
    resp = requests.get(endpoint, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []

# ==============================
# FUNCIONES MATRIX (ASÍNCRONAS)
# ==============================

async def check_user_exists(session, user_id):
    """Check if a Matrix user exists."""
    url = f"{HOMESERVER}/_synapse/admin/v2/users/{user_id}"
    headers = {'Authorization': f'Bearer {MATRIX_ADMIN_TOKEN}'}
    
    async with session.get(url, headers=headers, timeout=20) as resp:
        return resp.status == 200

async def create_matrix_user(session, localpart, email, password, displayname):
    user_id = f"@{localpart}:{SERVER_NAME}"
    
    # Check if user already exists
    exists = await check_user_exists(session, user_id)
    if exists:
        print(f"   → Usuario ya existe: {user_id}")
        return {"name": user_id}
    
    # Create new user
    url = f"{HOMESERVER}/_synapse/admin/v2/users/{user_id}"
    headers = {'Authorization': f'Bearer {MATRIX_ADMIN_TOKEN}', 'Content-Type': 'application/json'}
    body = {
            "password": password, 
            "threepids": [
                {
                    "medium": "email",
                    "address": email
                }
            ], 
            "displayname": displayname,
        }

    async with session.put(url, headers=headers, json=body, timeout=20) as resp:
        if resp.status in (200, 201):
            data = await resp.json()
            print(f"   → Usuario creado: {user_id}")
            return data
        else:
            text = await resp.text()
            raise RuntimeError(f"Error creando usuario {localpart}: {resp.status} {text}")

async def login_matrix_bot(session):
    url = f"{HOMESERVER}/_matrix/client/v3/login"
    body = {
        "type": "m.login.password",
        "identifier": {"type": "m.id.user", "user": USERNAME},
        "password": PASSWORD
    }
    async with session.post(url, json=body, timeout=20) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Error login bot: {resp.status} {await resp.text()}")
        data = await resp.json()
        return data["access_token"]

async def create_room(session, token, name, topic=None):
    url = f"{HOMESERVER}/_matrix/client/v3/createRoom"
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "name": name,
        "preset": "private_chat" if ROOM_VISIBILITY == "private" else "public_chat",
        "visibility": ROOM_VISIBILITY
    }
    if topic:
        body["topic"] = topic
    # Make room require knocking for entry instead of invite-only and set power levels
    body["initial_state"] = [
        {"type": "m.room.join_rules", "state_key": "", "content": {"join_rule": "knock"}},
        {
            "type": "m.room.power_levels",
            "state_key": "",
            "content": {
                # ensure creator (bot) keeps 100 PL so it can send state events immediately
                "users": {BOT_MXID: 100},
                # require moderator-level (50) to invite by default
                "invite": 50,
                "events_default": 0,
                "state_default": 50,
                "users_default": 0,
            },
        },
    ]

    max_retries = 3
    for attempt in range(max_retries):
        async with session.post(url, headers=headers, json=body, timeout=20) as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"   → Sala creada: {data['room_id']} ({name})")
                return data["room_id"]
            elif resp.status == 429:
                # Rate limited, wait and retry
                retry_data = await resp.json()
                retry_after_ms = retry_data.get("retry_after_ms", 5000)
                retry_after_s = retry_after_ms / 1000
                print(f"\n   ⚠️  RATE LIMIT ALCANZADO")
                print(f"   ℹ️  Añade el usuario '{USERNAME}' al rate limit override en el servidor Matrix")
                print(f"\n    Puedes modificarlo el configmap del servidor Synapse, añadiendo el usuario a la lista de excepciones.\n")
                print(f"   ⏳ Esperando {retry_after_s:.1f}s antes de reintentar...\n")
                await asyncio.sleep(retry_after_s+0.2)
                continue
            else:
                raise RuntimeError(f"Error creando sala {name}: {resp.status} {await resp.text()}")
    
    raise RuntimeError(f"Error creando sala {name}: Máximo de reintentos alcanzado")

async def join_user_to_room(session, room_id, user_id):
    """Use admin API to force join a user to a room.

    Some Synapse versions expect a JSON body: {"user_id": "@user:server"}.
    """
    url = f"{HOMESERVER}/_synapse/admin/v1/join/{room_id}"
    headers = {"Authorization": f"Bearer {MATRIX_ADMIN_TOKEN}", "Content-Type": "application/json"}
    body = {"user_id": user_id}
    
    max_retries = 3
    for attempt in range(max_retries):
        async with session.post(url, headers=headers, json=body, timeout=15) as resp:
            if resp.status in (200, 201):
                return
            elif resp.status == 429:
                # Rate limited, wait and retry
                retry_data = await resp.json()
                retry_after_ms = retry_data.get("retry_after_ms", 3000)
                retry_after_s = retry_after_ms / 1000
                if attempt == 0:  # Only show message on first rate limit
                    print(f"\n      ⚠️  RATE LIMIT ALCANZADO EN JOINS")
                    print(f"      ℹ️  Añade el usuario '{USERNAME}' al rate limit override en el servidor Matrix")
                    print(f"      ℹ️  Configuración: homeserver.yaml -> rc_joins exempt_user_ids")
                print(f"      ⏳ Esperando {retry_after_s:.1f}s...")
                await asyncio.sleep(retry_after_s)
                continue
            else:
                text = await resp.text()
                raise RuntimeError(f"Error uniendo {user_id} a la sala: {resp.status} {text}")
    
    raise RuntimeError(f"Error uniendo {user_id}: Máximo de reintentos alcanzado")

async def list_joined_members(session, token, room_id):
    """Return list of user_ids currently joined in the room using client API."""
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/members"
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(url, headers=headers, timeout=20) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Error obteniendo miembros de {room_id}: {resp.status} {await resp.text()}")
        data = await resp.json()
        members = []
        for ev in data.get("chunk", []):
            if ev.get("content", {}).get("membership") == "join":
                members.append(ev.get("state_key"))
        return members


async def list_invited_members(session, token, room_id):
    """Return list of user_ids with pending invites in the room."""
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/members"
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(url, headers=headers, timeout=20) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Error obteniendo miembros de {room_id}: {resp.status} {await resp.text()}")
        data = await resp.json()
        invited = []
        for ev in data.get("chunk", []):
            if ev.get("content", {}).get("membership") == "invite":
                invited.append(ev.get("state_key"))
        return invited

async def kick_user_from_room(session, token, room_id, user_id, reason="Room rotated, kicking all members"):
    """Kick a user from a room using client API. Returns True if kicked, False otherwise."""
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/kick"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"user_id": user_id, "reason": reason}
    async with session.post(url, headers=headers, json=body, timeout=15) as resp:
        if resp.status == 200:
            return True
        elif resp.status in (403, 404):
            # 403: lacks permission or target not kickable; 404: not found/not in room
            return False
        else:
            text = await resp.text()
            raise RuntimeError(f"Error expulsando {user_id} de {room_id}: {resp.status} {text}")

async def silence_all_members_from_room(session, token, room_id, bot_mxid):
    """Silence all joined members by setting power level to -10 (except the bot).

    Ensures the bot is in the room and has admin rights first.
    """
    if DRY_RUN:
        print(f"[DRY-RUN] Silenciar miembros en {room_id} (excepto {bot_mxid}) → no cambios reales")
        return
    # Asegurar que el bot está en la sala y es admin para poder modificar power levels
    try:
        await join_user_to_room(session, room_id, bot_mxid)
    except Exception:
        pass
    try:
        await make_user_room_admin(session, room_id, bot_mxid)
    except Exception:
        pass

    members = await list_joined_members(session, token, room_id)
    for mxid in members:
        if mxid == bot_mxid:
            continue
        try:
            ok = await set_user_power_level(session, token, room_id, mxid, level=-10)
            if ok:
                print(f"   → Silenciado {mxid} en sala antigua {room_id} (PL=-10)")
        except Exception as e:
            print(f"   ⚠️  No se pudo silenciar {mxid} en {room_id}: {e}")

    # Cancel any pending invites
    await cancel_pending_invites(session, token, room_id, bot_mxid)


async def cancel_pending_invites(session, token, room_id, bot_mxid):
    """Cancel all pending invites in the room by kicking invited users."""
    if DRY_RUN:
        print(f"[DRY-RUN] Cancelar invitaciones pendientes en {room_id} → no cambios reales")
        return
    try:
        invited = await list_invited_members(session, token, room_id)
    except Exception as e:
        print(f"   ⚠️  No se pudo obtener invitaciones pendientes de {room_id}: {e}")
        return
    for mxid in invited:
        if mxid == bot_mxid:
            continue
        try:
            ok = await kick_user_from_room(session, token, room_id, mxid, reason="Room closed, invite cancelled")
            if ok:
                print(f"   → Invitación cancelada para {mxid} en {room_id}")
        except Exception as e:
            print(f"   ⚠️  No se pudo cancelar invitación de {mxid} en {room_id}: {e}")


async def set_user_power_level(session, token, room_id, user_id, level: int):
    """Set a user's power level within a room, with rate-limit retries."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/state/m.room.power_levels"
    # Fetch current levels
    async with session.get(url, headers=headers, timeout=15) as resp:
        if resp.status == 404:
            power = {}
        elif resp.status != 200:
            raise RuntimeError(f"Error obteniendo power levels de {room_id}: {resp.status} {await resp.text()}")
        else:
            power = await resp.json()

    users_pl = power.get("users", {})
    if users_pl.get(user_id) == level:
        return True
    users_pl[user_id] = level
    power["users"] = users_pl

    max_retries = 3
    for attempt in range(max_retries):
        async with session.put(url, headers=headers, json=power, timeout=15) as resp:
            if resp.status in (200, 201):
                return True
            if resp.status == 429:
                data = await resp.json()
                retry_ms = data.get("retry_after_ms", 1500)
                await asyncio.sleep(retry_ms/1000.0 + 0.1)
                continue
            text = await resp.text()
            raise RuntimeError(f"Error estableciendo PL={level} para {user_id} en {room_id}: {resp.status} {text}")
    return True

async def make_user_room_admin(session, room_id, user_id):
    """Grant room admin to a user via Synapse Admin API (best-effort)."""
    url = f"{HOMESERVER}/_synapse/admin/v1/rooms/{room_id}/make_room_admin"
    headers = {"Authorization": f"Bearer {MATRIX_ADMIN_TOKEN}", "Content-Type": "application/json"}
    body = {"user_id": user_id}
    async with session.post(url, headers=headers, json=body, timeout=15) as resp:
        # 200/202 OK; 4xx can mean already admin or room not local; ignore
        if resp.status in (200, 202):
            return True
        return False

async def grant_moderator(session, token, room_id, user_id, level: int = 50):
    """Grant moderator (power level) to a user using client API.

    - Fetch current power levels
    - Set `users[user_id] = level` when missing or lower
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url_get = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/state/m.room.power_levels"
    async with session.get(url_get, headers=headers, timeout=15) as resp:
        if resp.status == 404:
            power = {}
        elif resp.status != 200:
            raise RuntimeError(f"Error obteniendo power levels de {room_id}: {resp.status} {await resp.text()}")
        else:
            power = await resp.json()

    users_pl = power.get("users", {})
    current = users_pl.get(user_id, 0)
    if current >= level:
        return True
    users_pl[user_id] = level
    power["users"] = users_pl

    url_put = url_get
    max_retries = 3
    for attempt in range(max_retries):
        async with session.put(url_put, headers=headers, json=power, timeout=15) as resp:
            if resp.status in (200, 201):
                return True
            if resp.status == 429:
                data = await resp.json()
                retry_ms = data.get("retry_after_ms", 1500)
                retry_s = (retry_ms / 1000.0) + 0.1
                if attempt == 0:
                    print(f"      ⚠️  RATE LIMIT al asignar moderator a {user_id} en {room_id}. Reintentando...")
                await asyncio.sleep(retry_s)
                continue
            text = await resp.text()
            raise RuntimeError(f"Error asignando moderator a {user_id} en {room_id}: {resp.status} {text}")
    return True


async def ensure_teacher_tutoring_room(
    session,
    conn,
    token,
    matrix_id: str,
    localpart: str,
    displayname: str,
):
    """Ensure each teacher has a dedicated tutoring room with shortcode=localpart."""
    if conn is None:
        return None

    teacher_row = await conn.fetchrow("SELECT id FROM users WHERE matrix_id = $1", matrix_id)
    if not teacher_row:
        return None

    teacher_db_id = teacher_row["id"]
    shortcode = (localpart or matrix_id.split(":", 1)[0].lstrip("@") or "tutoria").lower()

    existing = await conn.fetchrow(
        """
        SELECT room_id
        FROM rooms
        WHERE teacher_id = $1
          AND moodle_course_id IS NULL
          AND active = TRUE
        LIMIT 1
        """,
        teacher_db_id,
    )

    if existing:
        room_id = existing["room_id"]
        if DRY_RUN:
            print(f"[DRY-RUN] Sala de tutoría ya existe para {matrix_id}: {room_id}")
            return room_id
        try:
            await join_user_to_room(session, room_id, matrix_id)
        except Exception:
            pass
        try:
            await grant_moderator(session, token, room_id, matrix_id, level=50)
        except Exception as exc:
            print(f"   ⚠️  No se pudo asegurar moderador en tutoría {room_id} para {matrix_id}: {exc}")
        return room_id

    if DRY_RUN:
        print(f"[DRY-RUN] Crear sala de tutoría para {matrix_id} con shortcode '{shortcode}'")
        return None

    friendly_name = displayname or matrix_id
    topic = f"Tutorías privadas de {friendly_name}"
    try:
        tutoring_room_id = await create_room(
            session,
            token,
            f"Tutoría de {friendly_name}",
            topic,
        )
    except Exception as exc:
        print(f"   ⚠️  No se pudo crear la sala de tutoría para {matrix_id}: {exc}")
        return None

    await conn.execute(
        """
        INSERT INTO rooms (room_id, moodle_course_id, teacher_id, shortcode, active)
        VALUES ($1, NULL, $2, $3, TRUE)
        ON CONFLICT (room_id) DO NOTHING
        """,
        tutoring_room_id,
        teacher_db_id,
        shortcode,
    )

    try:
        await join_user_to_room(session, tutoring_room_id, matrix_id)
    except Exception as exc:
        print(f"   ⚠️  No se pudo unir al profesor {matrix_id} a su sala de tutoría: {exc}")
    try:
        await grant_moderator(session, token, tutoring_room_id, matrix_id, level=50)
    except Exception as exc:
        print(f"   ⚠️  No se pudo otorgar moderador en la sala de tutoría {tutoring_room_id}: {exc}")

    print(f"   → Sala de tutoría creada para {matrix_id}: {tutoring_room_id}")
    return tutoring_room_id

async def get_room_name(session, token, room_id):
    """Obtener el nombre actual de la sala (puede no existir)."""
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/state/m.room.name"
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(url, headers=headers, timeout=15) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data.get("name")
        elif resp.status == 404:
            return None
        else:
            text = await resp.text()
            raise RuntimeError(f"Error obteniendo nombre de sala {room_id}: {resp.status} {text}")

async def set_room_name(session, token, room_id, name):
    """Establecer el nombre de la sala."""
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/state/m.room.name"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"name": name}
    async with session.put(url, headers=headers, json=body, timeout=15) as resp:
        if resp.status not in (200, 201):
            text = await resp.text()
            raise RuntimeError(f"Error estableciendo nombre de sala {room_id}: {resp.status} {text}")

def academic_closed_prefix(created_at: datetime) -> str:
    """Build prefix like '(25/26 CLOSED) ' based on academic year from created_at.

    Academic year starts in September. Two-digit year numbers.
    """
    year = created_at.year
    month = created_at.month
    start_year = year if month >= 9 else year - 1
    xx = start_year % 100
    yy = (start_year + 1) % 100
    return f"({xx:02d}/{yy:02d} CLOSED) "

async def ensure_room_name_prefixed(session, token, room_id, prefix: str):
    """Ensure room name starts with given prefix; set if missing."""
    try:
        current = await get_room_name(session, token, room_id)
        if current is None:
            new_name = prefix.strip()
        elif current.startswith(prefix):
            return
        else:
            new_name = prefix + current
        await set_room_name(session, token, room_id, new_name)
        print(f"   → Renombrada sala {room_id} a '{new_name}'")
    except Exception as e:
        print(f"   ⚠️  No se pudo renombrar sala {room_id}: {e}")

async def deactivate_all_rooms_and_kick(conn, session, bot_token, bot_mxid):
    """Desactiva todas las salas en la base de datos y expulsa a todos los usuarios de cada una."""
    if DRY_RUN:
        # Mostrar un resumen de cuántas salas activas hay y cuáles se renombrarán/inhabilitarán
        rows = await conn.fetch(
            """
            SELECT room_id, created_at
            FROM rooms
            WHERE active = TRUE
            ORDER BY created_at DESC
            """
        )
        print("\n[DRY-RUN] Plan de cierre de salas activas:")
        for r in rows:
            rmid = r["room_id"]
            created_at = r["created_at"] or datetime.utcnow()
            prefix = academic_closed_prefix(created_at)
            # Obtener miembros actuales para mostrar conteo (solo lectura)
            try:
                members = await list_joined_members(session, bot_token, rmid)
                count = len([m for m in members if m != bot_mxid])
            except Exception as e:
                count = "?"
                print(f"   ⚠️  No se pudieron listar miembros de {rmid}: {e}")
            print(f"  - {rmid}: renombrar a '{prefix}<nombre_actual>', marcar inactive, silenciar {count} miembros")
        print(f"[DRY-RUN] Total salas a cerrar: {len(rows)}\n")
        return

    print("\n=== Desactivando todas las salas y expulsando miembros ===")
    rows = await conn.fetch(
        """
        SELECT room_id
        FROM rooms
        WHERE active = TRUE
        """
    )
    room_ids = [r["room_id"] for r in rows if r["room_id"]]
    for rmid in room_ids:
        try:
            # Obtener created_at para prefijo académico de esta sala
            rec = await conn.fetchrow("SELECT created_at FROM rooms WHERE room_id = $1", rmid)
            created_at = rec["created_at"] if rec and rec["created_at"] else datetime.utcnow()
            prefix = academic_closed_prefix(created_at)
            await ensure_room_name_prefixed(session, bot_token, rmid, prefix)
            await silence_all_members_from_room(session, bot_token, rmid, bot_mxid)
        except Exception as e:
            print(f"[AVISO] No se pudieron expulsar miembros de {rmid}: {e}")

    # Marcar todas como inactivas
    await conn.execute("UPDATE rooms SET active = FALSE WHERE active = TRUE")
    print(f"[OK] Desactivadas {len(room_ids)} salas y expulsados sus miembros")

# ==============================
# PRINCIPAL
# ==============================

async def main():
    print("=== Sincronizando usuarios y cursos ===")
    courses = get_courses()
    print(f"Asignaturas obtenidas: {len(courses)}\n")

    async with aiohttp.ClientSession() as session:
        # In dry-run, still authenticate to allow GET calls to client API.
        token = await login_matrix_bot(session)
        print(f"[+] Bot autenticado correctamente\n")

        # Conectar a la base de datos en todos los modos (en DRY-RUN solo lectura)
        conn = await asyncpg.connect(PG_DSN)
        if not DRY_RUN:
            # Crear esquema si es necesario
            schema_file = Path(__file__).parent / "bot/core/db/postgres/schema.sql"
            if not schema_file.exists():
                raise FileNotFoundError(f"No se encontró {schema_file}")
            sql = schema_file.read_text()
            await conn.execute(sql)

        # Paso opcional: desactivar salas; en DRY-RUN solo mostrar el plan
        if DEACTIVATE_ALL_ROOMS:
            bot_mxid = BOT_MXID
            # Si aún no tenemos token, inicie sesión
            if token is None:
                token = await login_matrix_bot(session)
            await deactivate_all_rooms_and_kick(conn, session, token, bot_mxid)

        for course in courses:
            cid = course["id"]
            cname = course["fullname"]
            cshortname = course["shortname"]
            if cid == 1:
                continue

            print(f"\n=== Procesando curso: {cname} (ID={cid}) ===")

            users = get_course_users(cid)
            print(f"Usuarios inscritos: {len(users)}")

            room_id = None
            room_id_teachers = None
            old_rooms = []
            if not DRY_RUN:
                # Identify previously active rooms for this course (captured before we deactivate)
                old_rooms = await conn.fetch(
                    """
                    SELECT room_id, created_at
                    FROM rooms
                    WHERE teacher_id = $1
                      AND shortcode = $2
                      AND active = TRUE
                    """,
                    None, cshortname,
                )

                # Create new rooms
                topic = f"Grupo de la asignatura {cname}"
                room_id = await create_room(session, token, cname, topic)
                room_id_teachers = await create_room(session, token, f"{cname} - Profesores", f"Sala de profesores para {cname}")

                # Insert or replace active rooms in the database
                async with conn.transaction():
                    # Deactivate previous active main room
                    await conn.execute(
                        """
                        UPDATE rooms
                        SET active = FALSE
                        WHERE teacher_id = $1
                          AND shortcode = $2
                          AND active = TRUE
                        """,
                        None, cshortname,
                    )

                    # Insert new main room as active
                    await conn.execute(
                        """
                        INSERT INTO rooms (room_id, moodle_course_id, teacher_id, shortcode, active)
                        VALUES ($1, $2, $3, $4, TRUE)
                        ON CONFLICT (room_id) DO UPDATE
                        SET room_id = EXCLUDED.room_id
                        """,
                        room_id, cid, None, cshortname,
                    )

                    # Deactivate previous active teachers room
                    await conn.execute(
                        """
                        UPDATE rooms
                        SET active = FALSE
                        WHERE teacher_id = $1
                          AND shortcode = $2
                          AND active = TRUE
                        """,
                        None, cshortname + "_teachers",
                    )

                    # Insert new teachers room as active
                    await conn.execute(
                        """
                        INSERT INTO rooms (room_id, moodle_course_id, teacher_id, shortcode, active)
                        VALUES ($1, $2, $3, $4, TRUE)
                        ON CONFLICT (room_id) DO UPDATE
                        SET room_id = EXCLUDED.room_id
                        """,
                        room_id_teachers, cid, None, cshortname + "_teachers",
                    )

                print(f"[CREADA/ACTUALIZADA] Salas '{cname}' ({room_id} y {room_id_teachers})")

                # Kick all members from previously active (now deactivated) room(s)
                try:
                    bot_mxid = BOT_MXID
                    for rec in old_rooms:
                        old_room_id = rec["room_id"]
                        created_at = rec["created_at"] if "created_at" in rec else None
                        if old_room_id:
                            prefix = academic_closed_prefix(created_at or datetime.utcnow())
                            if DRY_RUN:
                                print(f"[DRY-RUN] '{cshortname}': renombrar {old_room_id} a '{prefix}<nombre_actual>' y silenciar miembros")
                            else:
                                await ensure_room_name_prefixed(session, token, old_room_id, prefix)
                                await silence_all_members_from_room(session, token, old_room_id, bot_mxid)
                except Exception as e:
                    print(f"[AVISO] No se pudieron expulsar miembros de salas antiguas: {e}")

            for u in users:
                email = u.get("email")
                if not email:
                    continue

                localpart = safe_localpart(email, f"user{u['id']}")
                displayname = f"{u.get('firstname', '')} {u.get('lastname', '')}".strip() or localpart
                matrix_id = matrix_user_id_from_email(email, SERVER_NAME)
                moodle_id = u.get("id")

                # Determinar si es profesor
                roles = [r.get("shortname", "") for r in u.get("roles", [])]
                is_teacher = any(r in ("editingteacher", "teacher") for r in roles)

                if DRY_RUN:
                    print(f"[DRY-RUN] {matrix_id} ({displayname}) -> moodle_id={moodle_id} teacher={is_teacher}")
                    continue

                try:
                    # Crear usuario si no existe
                    await create_matrix_user(session, localpart, email, localpart, displayname)
                    
                    # Insertar en base de datos
                    await conn.execute("""
                        INSERT INTO users (matrix_id, moodle_id, is_teacher)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (matrix_id) DO UPDATE
                        SET
                            moodle_id = EXCLUDED.moodle_id,
                            is_teacher = CASE
                                WHEN users.is_teacher = FALSE AND EXCLUDED.is_teacher = TRUE THEN TRUE
                                ELSE users.is_teacher
                            END
                    """, matrix_id, moodle_id, is_teacher)

                    # Unir usuario a las salas usando admin API
                    if room_id:
                        await join_user_to_room(session, room_id, matrix_id)
                        if is_teacher:
                            await join_user_to_room(session, room_id_teachers, matrix_id)
                            # Grant moderator to teacher in both rooms
                            try:
                                await grant_moderator(session, token, room_id, matrix_id, level=50)
                                await grant_moderator(session, token, room_id_teachers, matrix_id, level=50)
                                print(f"   → Moderador asignado a {matrix_id}")
                            except Exception as e:
                                print(f"   ⚠️  No se pudo asignar moderador a {matrix_id}: {e}")
                        print(f"   → Unido {matrix_id} ({'profesor' if is_teacher else 'alumno'})")

                    if is_teacher:
                        await ensure_teacher_tutoring_room(
                            session,
                            conn,
                            token,
                            matrix_id,
                            localpart,
                            displayname,
                        )

                except Exception as e:
                    print(f"[ERROR] {matrix_id}: {e}")

        if conn:
            await conn.close()

    print("\n=== Sincronización completa ===")


if __name__ == "__main__":
    asyncio.run(main())
