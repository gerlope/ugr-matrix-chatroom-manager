# core/db/postgres/queries.py
"""
Consulta y manipulación de datos en PostgreSQL.
"""

from core.db.constants import *
import core.db.postgres.conn as conn_module
from core.db.postgres.utils import db_safe

# ────────────────────────────────
# Users
# ────────────────────────────────

@db_safe(default=None)
async def get_user_by_id(user_id: str):
    """Obtiene un usuario por su matrix_id."""
    async with conn_module.pool.acquire() as conn:
        return await conn.fetchrow(
            f"SELECT * FROM {TABLE_USERS} WHERE {COL_USER_ID} = $1",
            user_id,
        )

@db_safe(default=None)
async def get_user_by_matrix_id(matrix_user_id: str):
    """Obtiene un usuario por su matrix_id."""
    async with conn_module.pool.acquire() as conn:
        return await conn.fetchrow(
            f"SELECT * FROM {TABLE_USERS} WHERE {COL_USER_MATRIX_ID} = $1",
            matrix_user_id,
        )


@db_safe(default=None)
async def get_user_by_moodle_id(moodle_user_id: int):
    """Obtiene un usuario por su moodle_id."""
    async with conn_module.pool.acquire() as conn:
        return await conn.fetchrow(
            f"SELECT * FROM {TABLE_USERS} WHERE {COL_USER_MOODLE_ID} = $1",
            moodle_user_id,
        )


# ────────────────────────────────
# Rooms
# ────────────────────────────────

@db_safe(default=None)
async def get_room_by_matrix_id(matrix_room_id: str):
    """Obtiene los datos de una sala por su Matrix room_id."""
    async with conn_module.pool.acquire() as conn:
        return await conn.fetchrow(
            f"SELECT * FROM {TABLE_ROOMS} WHERE {COL_ROOM_ROOM_ID} = $1",
            matrix_room_id,
        )


@db_safe(default=[])
async def get_active_rooms_for_teacher_and_course(course_id: int, teacher_user_id: int):
    """Devuelve las salas activas de un curso asociadas a un profesor específico."""
    async with conn_module.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {COL_ROOM_ID}, {COL_ROOM_ROOM_ID}, {COL_ROOM_SHORTCODE}
            FROM {TABLE_ROOMS}
            WHERE {COL_ROOM_MOODLE_COURSE_ID} = $1
              AND {COL_ROOM_TEACHER_ID} = $2
              AND {COL_ROOM_ACTIVE} = TRUE
            ORDER BY {COL_ROOM_SHORTCODE}
            """,
            course_id,
            teacher_user_id,
        )
    return [dict(row) for row in rows]


@db_safe(default=None)
async def get_teacher_tutoring_room(teacher_user_id: int):
    """Obtiene la sala de tutorías (sin curso asociado) de un profesor."""
    async with conn_module.pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT *
            FROM {TABLE_ROOMS}
            WHERE {COL_ROOM_TEACHER_ID} = $1
              AND {COL_ROOM_MOODLE_COURSE_ID} IS NULL
              AND {COL_ROOM_ACTIVE} = TRUE
            ORDER BY {COL_ROOM_CREATED_AT} DESC
            LIMIT 1
            """,
            teacher_user_id,
        )


# ────────────────────────────────
# Reactions
# ────────────────────────────────

@db_safe(default=[])
async def get_reacciones_por_profesor(teacher_matrix_id: str):
    """Obtiene todas las reacciones puestas por un profesor (usando su matrix_id)."""
    async with conn_module.pool.acquire() as conn:
        query = f"""
            SELECT r.{COL_REACTION_EMOJI}, r.{COL_REACTION_COUNT}, r.{COL_REACTION_ROOM_ID},
                   s.{COL_USER_MOODLE_ID} AS {JOINED_REACTION_STUDENT_MOODLE_ID}, 
                   s.{COL_USER_MATRIX_ID} as {JOINED_REACTION_STUDENT_MATRIX_ID},
                   room.{COL_ROOM_SHORTCODE} AS {JOINED_REACTION_ROOM_SHORTCODE},
                   room.{COL_ROOM_MOODLE_COURSE_ID} AS {JOINED_REACTION_ROOM_MOODLE_COURSE_ID}
            FROM {TABLE_REACTIONS} r
            JOIN {TABLE_USERS} t ON r.{COL_REACTION_TEACHER_ID} = t.{COL_USER_ID}
            JOIN {TABLE_USERS} s ON r.{COL_REACTION_STUDENT_ID} = s.{COL_USER_ID}
            JOIN {TABLE_ROOMS} room ON r.{COL_REACTION_ROOM_ID} = room.{COL_ROOM_ID}
            WHERE t.{COL_USER_MATRIX_ID} = $1
            ORDER BY r.{COL_REACTION_ROOM_ID}, s.{COL_USER_MOODLE_ID};
        """
        rows = await conn.fetch(query, teacher_matrix_id)
    return [dict(row) for row in rows]


@db_safe(default=[])
async def get_reacciones_por_estudiante(student_matrix_id: str):
    """Obtiene todas las reacciones recibidas por un estudiante (usando su matrix_id)."""
    async with conn_module.pool.acquire() as conn:
        query = f"""
            SELECT r.{COL_REACTION_EMOJI}, r.{COL_REACTION_COUNT}, r.{COL_REACTION_ROOM_ID},
                   t.{COL_USER_MOODLE_ID} AS {JOINED_REACTION_TEACHER_MOODLE_ID},
                   t.{COL_USER_MATRIX_ID} AS {JOINED_REACTION_TEACHER_MATRIX_ID},
                   room.{COL_ROOM_SHORTCODE} AS {JOINED_REACTION_ROOM_SHORTCODE},
                   room.{COL_ROOM_MOODLE_COURSE_ID} AS {JOINED_REACTION_ROOM_MOODLE_COURSE_ID}
            FROM {TABLE_REACTIONS} r
            JOIN {TABLE_USERS} s ON r.{COL_REACTION_STUDENT_ID} = s.{COL_USER_ID}
            JOIN {TABLE_USERS} t ON r.{COL_REACTION_TEACHER_ID} = t.{COL_USER_ID}
            JOIN {TABLE_ROOMS} room ON r.{COL_REACTION_ROOM_ID} = room.{COL_ROOM_ID}
            WHERE s.{COL_USER_MATRIX_ID} = $1
            ORDER BY r.{COL_REACTION_ROOM_ID}, t.{COL_USER_MOODLE_ID};
        """
        rows = await conn.fetch(query, student_matrix_id)
    return [dict(row) for row in rows]


@db_safe(default=False)
async def add_or_increase_reaccion(
    teacher_id: int, 
    student_id: int, 
    room_id: str, 
    reaction_type: str, 
    increment: int = 1
):
    """
    Añade una reación a la tabla o incrementa su contador si ya existe.
    """
    async with conn_module.pool.acquire() as conn:
        await conn.execute(f"""
            INSERT INTO {TABLE_REACTIONS} 
                ({COL_REACTION_TEACHER_ID}, 
                 {COL_REACTION_STUDENT_ID}, 
                 {COL_REACTION_ROOM_ID}, 
                 {COL_REACTION_EMOJI}, 
                 {COL_REACTION_COUNT})
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT ({COL_REACTION_TEACHER_ID}, 
                         {COL_REACTION_STUDENT_ID}, 
                         {COL_REACTION_ROOM_ID}, 
                         {COL_REACTION_EMOJI})
            DO UPDATE SET
                {COL_REACTION_COUNT} = {TABLE_REACTIONS}.{COL_REACTION_COUNT} + EXCLUDED.{COL_REACTION_COUNT},
                {COL_REACTION_LAST_UPDATED} = NOW();
        """, teacher_id, student_id, room_id, reaction_type, increment)
    return True


@db_safe(default=False)
async def decrease_or_delete_reaccion(
    teacher_id: int,
    student_id: int,
    room_id: str,
    reaction_type: str,
    decrement: int = 1
):
    """
    Disminuye el contador de una reacción. 
    Si el contador actual es menor o igual al decremento, elimina la reacción.
    """
    async with conn_module.pool.acquire() as conn:
        await conn.execute(f"""
            DELETE FROM {TABLE_REACTIONS}
            WHERE {COL_REACTION_TEACHER_ID} = $1
              AND {COL_REACTION_STUDENT_ID} = $2
              AND {COL_REACTION_ROOM_ID} = $3
              AND {COL_REACTION_EMOJI} = $4
              AND {COL_REACTION_COUNT} <= $5;

            UPDATE {TABLE_REACTIONS}
            SET {COL_REACTION_COUNT} = {COL_REACTION_COUNT} - $5,
                {COL_REACTION_LAST_UPDATED} = NOW()
            WHERE {COL_REACTION_TEACHER_ID} = $1
              AND {COL_REACTION_STUDENT_ID} = $2
              AND {COL_REACTION_ROOM_ID} = $3
              AND {COL_REACTION_EMOJI} = $4
              AND {COL_REACTION_COUNT} > $5;
        """, teacher_id, student_id, room_id, reaction_type, decrement)
    return True

