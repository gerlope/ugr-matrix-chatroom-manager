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


@db_safe(default=[])
async def get_teacher_availability_windows(teacher_user_id: int):
    """Devuelve las franjas horarias de disponibilidad para el profesor dado."""
    async with conn_module.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {COL_TEACHER_AVAILABILITY_DAY_OF_WEEK} AS day_of_week,
                   {COL_TEACHER_AVAILABILITY_START_TIME} AS start_time,
                   {COL_TEACHER_AVAILABILITY_END_TIME} AS end_time
            FROM {TABLE_TEACHER_AVAILABILITY}
            WHERE {COL_TEACHER_AVAILABILITY_TEACHER_ID} = $1
            ORDER BY {COL_TEACHER_AVAILABILITY_DAY_OF_WEEK}, {COL_TEACHER_AVAILABILITY_START_TIME}
            """,
            teacher_user_id,
        )
    return [dict(row) for row in rows]


@db_safe(default=[])
async def get_general_rooms_for_courses(course_ids: list):
    """Devuelve las salas generales (teacher_id IS NULL) activas para una lista de cursos."""
    if not course_ids:
        return []
    async with conn_module.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {COL_ROOM_ID}, {COL_ROOM_ROOM_ID}, {COL_ROOM_SHORTCODE}, {COL_ROOM_MOODLE_COURSE_ID}
            FROM {TABLE_ROOMS}
            WHERE {COL_ROOM_MOODLE_COURSE_ID} = ANY($1::int[])
              AND {COL_ROOM_TEACHER_ID} IS NULL
              AND {COL_ROOM_ACTIVE} = TRUE
            ORDER BY {COL_ROOM_MOODLE_COURSE_ID}, {COL_ROOM_SHORTCODE}
            """,
            course_ids,
        )
    return [dict(row) for row in rows]


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


# ────────────────────────────────
# Questions
# ────────────────────────────────

@db_safe(default=[])
async def get_all_questions_for_courses(course_ids: list):
    """
    Devuelve todas las preguntas para una lista de cursos (activas o no).
    Incluye información sobre el estado actual de cada pregunta.
    """
    if not course_ids:
        return []
    async with conn_module.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
                 SELECT q.{COL_QUESTION_ID},
                     q.{COL_QUESTION_TITLE},
                     q.{COL_QUESTION_BODY},
                     q.{COL_QUESTION_QTYPE},
                     q.{COL_QUESTION_START_AT},
                     q.{COL_QUESTION_END_AT},
                     q.{COL_QUESTION_MANUAL_ACTIVE},
                     q.{COL_QUESTION_CLOSE_TRIGGERED},
                     q.{COL_QUESTION_ALLOW_MULTIPLE_SELECTIONS},
                     q.{COL_QUESTION_ALLOW_MULTIPLE_SUBMISSIONS},
                     q.{COL_QUESTION_CLOSE_ON_FIRST_CORRECT},
                     q.{COL_QUESTION_ALLOW_LATE},
                   r.{COL_ROOM_ID} AS room_db_id,
                   r.{COL_ROOM_ROOM_ID} AS room_matrix_id,
                   r.{COL_ROOM_SHORTCODE} AS room_shortcode,
                   r.{COL_ROOM_MOODLE_COURSE_ID} AS room_course_id,
                   r.{COL_ROOM_MOODLE_GROUP} AS room_moodle_group,
                   CASE
                       WHEN q.{COL_QUESTION_CLOSE_TRIGGERED} = TRUE THEN 'closed'
                       WHEN q.{COL_QUESTION_MANUAL_ACTIVE} = TRUE THEN 'active'
                       WHEN q.{COL_QUESTION_START_AT} IS NOT NULL
                            AND q.{COL_QUESTION_START_AT} <= NOW()
                            AND (q.{COL_QUESTION_END_AT} IS NULL OR q.{COL_QUESTION_END_AT} >= NOW()) THEN 'active'
                       WHEN q.{COL_QUESTION_START_AT} IS NULL
                            AND q.{COL_QUESTION_END_AT} IS NOT NULL
                            AND q.{COL_QUESTION_END_AT} >= NOW() THEN 'active'
                       WHEN q.{COL_QUESTION_START_AT} IS NOT NULL
                            AND q.{COL_QUESTION_START_AT} > NOW() THEN 'scheduled'
                       WHEN q.{COL_QUESTION_END_AT} IS NOT NULL
                            AND q.{COL_QUESTION_END_AT} < NOW() THEN 'ended'
                       ELSE 'inactive'
                   END AS question_status
            FROM {TABLE_QUESTIONS} q
            JOIN {TABLE_ROOMS} r ON q.{COL_QUESTION_ROOM_ID} = r.{COL_ROOM_ID}
            WHERE r.{COL_ROOM_MOODLE_COURSE_ID} = ANY($1::int[])
              AND r.{COL_ROOM_ACTIVE} = TRUE
            ORDER BY r.{COL_ROOM_SHORTCODE}, q.{COL_QUESTION_ID}
            """,
            course_ids,
        )
    return [dict(row) for row in rows]


@db_safe(default=[])
async def get_active_questions_for_courses(course_ids: list):
    """
    Devuelve las preguntas activas para una lista de cursos.
    Una pregunta está activa si:
    - manual_active = TRUE, o
    - start_at <= now AND (end_at IS NULL OR end_at >= now), o
    - start_at IS NULL AND end_at >= now
    Excluye preguntas con close_triggered = TRUE.
    """
    if not course_ids:
        return []
    async with conn_module.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
                 SELECT q.{COL_QUESTION_ID},
                     q.{COL_QUESTION_TITLE},
                     q.{COL_QUESTION_BODY},
                     q.{COL_QUESTION_QTYPE},
                     q.{COL_QUESTION_START_AT},
                     q.{COL_QUESTION_END_AT},
                     q.{COL_QUESTION_MANUAL_ACTIVE},
                     q.{COL_QUESTION_ALLOW_MULTIPLE_SELECTIONS},
                     q.{COL_QUESTION_ALLOW_MULTIPLE_SUBMISSIONS},
                     q.{COL_QUESTION_CLOSE_ON_FIRST_CORRECT},
                     q.{COL_QUESTION_ALLOW_LATE},
                   r.{COL_ROOM_ID} AS room_db_id,
                   r.{COL_ROOM_ROOM_ID} AS room_matrix_id,
                   r.{COL_ROOM_SHORTCODE} AS room_shortcode,
                   r.{COL_ROOM_MOODLE_COURSE_ID} AS room_course_id,
                   r.{COL_ROOM_MOODLE_GROUP} AS room_moodle_group
            FROM {TABLE_QUESTIONS} q
            JOIN {TABLE_ROOMS} r ON q.{COL_QUESTION_ROOM_ID} = r.{COL_ROOM_ID}
            WHERE r.{COL_ROOM_MOODLE_COURSE_ID} = ANY($1::int[])
              AND r.{COL_ROOM_ACTIVE} = TRUE
              AND q.{COL_QUESTION_CLOSE_TRIGGERED} = FALSE
              AND (
                  q.{COL_QUESTION_MANUAL_ACTIVE} = TRUE
                  OR (
                      q.{COL_QUESTION_START_AT} IS NOT NULL
                      AND q.{COL_QUESTION_START_AT} <= NOW()
                      AND (q.{COL_QUESTION_END_AT} IS NULL OR q.{COL_QUESTION_END_AT} >= NOW())
                  )
                  OR (
                      q.{COL_QUESTION_START_AT} IS NULL
                      AND q.{COL_QUESTION_END_AT} IS NOT NULL
                      AND q.{COL_QUESTION_END_AT} >= NOW()
                  )
              )
            ORDER BY r.{COL_ROOM_SHORTCODE}, q.{COL_QUESTION_ID}
            """,
            course_ids,
        )
    return [dict(row) for row in rows]


@db_safe(default=[])
async def get_question_options(question_id: int):
    """Devuelve las opciones de una pregunta."""
    async with conn_module.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {COL_QUESTION_OPTION_ID},
                   {COL_QUESTION_OPTION_KEY},
                   {COL_QUESTION_OPTION_TEXT},
                   {COL_QUESTION_OPTION_IS_CORRECT},
                   {COL_QUESTION_OPTION_POSITION}
            FROM {TABLE_QUESTION_OPTIONS}
            WHERE {COL_QUESTION_OPTION_QUESTION_ID} = $1
            ORDER BY {COL_QUESTION_OPTION_POSITION}, {COL_QUESTION_OPTION_KEY}
            """,
            question_id,
        )
    return [dict(row) for row in rows]


@db_safe(default=False)
async def is_tutoring_room(matrix_room_id: str) -> bool:
    """
    Returns True if the room is a tutoring room (no moodle_course_id) and active.
    """
    async with conn_module.pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT 1
            FROM {TABLE_ROOMS}
            WHERE {COL_ROOM_ROOM_ID} = $1
              AND {COL_ROOM_MOODLE_COURSE_ID} IS NULL
              AND {COL_ROOM_ACTIVE} = TRUE
            LIMIT 1
            """,
            matrix_room_id,
        )
    return row is not None


@db_safe(default=[])
async def get_all_currently_active_questions():
    """
    Devuelve todas las preguntas activas en este momento.
    Una pregunta está activa si:
    - manual_active = TRUE, o
    - start_at <= now AND (end_at IS NULL OR end_at >= now), o
    - start_at IS NULL AND end_at >= now
    Excluye preguntas con close_triggered = TRUE.
    """
    async with conn_module.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT q.{COL_QUESTION_ID},
                   q.{COL_QUESTION_TITLE},
                   q.{COL_QUESTION_BODY},
                   q.{COL_QUESTION_QTYPE},
                   q.{COL_QUESTION_START_AT},
                   q.{COL_QUESTION_END_AT},
                   q.{COL_QUESTION_MANUAL_ACTIVE},
                   q.{COL_QUESTION_ALLOW_MULTIPLE_SELECTIONS},
                   q.{COL_QUESTION_ALLOW_MULTIPLE_SUBMISSIONS},
                   q.{COL_QUESTION_CLOSE_ON_FIRST_CORRECT},
                   q.{COL_QUESTION_ALLOW_LATE},
                   r.{COL_ROOM_ID} AS room_db_id,
                   r.{COL_ROOM_ROOM_ID} AS room_matrix_id,
                   r.{COL_ROOM_SHORTCODE} AS room_shortcode
            FROM {TABLE_QUESTIONS} q
            JOIN {TABLE_ROOMS} r ON q.{COL_QUESTION_ROOM_ID} = r.{COL_ROOM_ID}
            WHERE r.{COL_ROOM_ACTIVE} = TRUE
              AND q.{COL_QUESTION_CLOSE_TRIGGERED} = FALSE
              AND (
                  q.{COL_QUESTION_MANUAL_ACTIVE} = TRUE
                  OR (
                      q.{COL_QUESTION_START_AT} IS NOT NULL
                      AND q.{COL_QUESTION_START_AT} <= NOW()
                      AND (q.{COL_QUESTION_END_AT} IS NULL OR q.{COL_QUESTION_END_AT} >= NOW())
                  )
                  OR (
                      q.{COL_QUESTION_START_AT} IS NULL
                      AND q.{COL_QUESTION_END_AT} IS NOT NULL
                      AND q.{COL_QUESTION_END_AT} >= NOW()
                  )
              )
            ORDER BY q.{COL_QUESTION_ID}
            """
        )
    return [dict(row) for row in rows]


# ────────────────────────────────
# Question Responses
# ────────────────────────────────

@db_safe(default=None)
async def get_question_by_id(question_id: int):
    """Obtiene una pregunta por su ID con toda la información necesaria."""
    async with conn_module.pool.acquire() as conn:
        return await conn.fetchrow(
            f"""
            SELECT q.*,
                   r.{COL_ROOM_ROOM_ID} AS room_matrix_id,
                   r.{COL_ROOM_MOODLE_COURSE_ID} AS room_course_id,
                   r.{COL_ROOM_MOODLE_GROUP} AS room_moodle_group
            FROM {TABLE_QUESTIONS} q
            LEFT JOIN {TABLE_ROOMS} r ON q.{COL_QUESTION_ROOM_ID} = r.{COL_ROOM_ID}
            WHERE q.{COL_QUESTION_ID} = $1
            """,
            question_id,
        )

@db_safe(default=None)
async def get_student_response_count(question_id: int, student_id: int):
    """Obtiene el número de respuestas del estudiante para una pregunta."""
    async with conn_module.pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT COUNT(*) as count, MAX({COL_RESPONSE_VERSION}) as max_version
            FROM {TABLE_QUESTION_RESPONSES}
            WHERE {COL_RESPONSE_QUESTION_ID} = $1
              AND {COL_RESPONSE_STUDENT_ID} = $2
            """,
            question_id,
            student_id,
        )
    return dict(row) if row else {"count": 0, "max_version": 0}


@db_safe(default=[])
async def get_student_responses_for_question(question_id: int, student_id: int):
    """Obtiene todas las respuestas de un estudiante para una pregunta, con info del corrector."""
    async with conn_module.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT r.{COL_RESPONSE_ID},
                   r.{COL_RESPONSE_ANSWER_TEXT},
                   r.{COL_RESPONSE_OPTION_ID},
                   r.{COL_RESPONSE_SUBMITTED_AT},
                   r.{COL_RESPONSE_IS_GRADED},
                   r.{COL_RESPONSE_SCORE},
                   r.{COL_RESPONSE_GRADER_ID},
                   r.{COL_RESPONSE_FEEDBACK},
                   r.{COL_RESPONSE_VERSION},
                   r.{COL_RESPONSE_LATE},
                   g.{COL_USER_MATRIX_ID} AS grader_matrix_id
            FROM {TABLE_QUESTION_RESPONSES} r
            LEFT JOIN {TABLE_USERS} g ON r.{COL_RESPONSE_GRADER_ID} = g.{COL_USER_ID}
            WHERE r.{COL_RESPONSE_QUESTION_ID} = $1
              AND r.{COL_RESPONSE_STUDENT_ID} = $2
            ORDER BY r.{COL_RESPONSE_VERSION} ASC
            """,
            question_id,
            student_id,
        )
    return [dict(row) for row in rows]


@db_safe(default=[])
async def get_response_option_ids(response_id: int):
    """Obtiene los IDs de opciones seleccionadas para una respuesta."""
    async with conn_module.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {COL_RESPONSE_OPTIONS_OPTION_ID}
            FROM {TABLE_RESPONSE_OPTIONS}
            WHERE {COL_RESPONSE_OPTIONS_RESPONSE_ID} = $1
            """,
            response_id,
        )
    return [row[COL_RESPONSE_OPTIONS_OPTION_ID] for row in rows]


@db_safe(default=None)
async def insert_question_response(
    question_id: int,
    student_id: int,
    answer_text: str = None,
    option_id: int = None,
    score: float = None,
    is_graded: bool = False,
    response_version: int = 1,
    late: bool = False,
):
    """Inserta una respuesta a una pregunta."""
    async with conn_module.pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            INSERT INTO {TABLE_QUESTION_RESPONSES}
                ({COL_RESPONSE_QUESTION_ID}, {COL_RESPONSE_STUDENT_ID}, 
                 {COL_RESPONSE_ANSWER_TEXT}, {COL_RESPONSE_OPTION_ID},
                 {COL_RESPONSE_SCORE}, {COL_RESPONSE_IS_GRADED},
                 {COL_RESPONSE_VERSION}, {COL_RESPONSE_LATE})
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING {COL_RESPONSE_ID}
            """,
            question_id,
            student_id,
            answer_text,
            option_id,
            score,
            is_graded,
            response_version,
            late,
        )
    return row[COL_RESPONSE_ID] if row else None


@db_safe(default=False)
async def insert_response_options(response_id: int, option_ids: list):
    """Inserta las opciones seleccionadas para una respuesta multi-select."""
    if not option_ids:
        return True
    async with conn_module.pool.acquire() as conn:
        for opt_id in option_ids:
            await conn.execute(
                f"""
                INSERT INTO {TABLE_RESPONSE_OPTIONS}
                    ({COL_RESPONSE_OPTIONS_RESPONSE_ID}, {COL_RESPONSE_OPTIONS_OPTION_ID})
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                response_id,
                opt_id,
            )
    return True


@db_safe(default=False)
async def set_question_close_triggered(question_id: int):
    """Marca una pregunta como cerrada (close_triggered = TRUE)."""
    async with conn_module.pool.acquire() as conn:
        await conn.execute(
            f"""
            UPDATE {TABLE_QUESTIONS}
            SET {COL_QUESTION_CLOSE_TRIGGERED} = TRUE
            WHERE {COL_QUESTION_ID} = $1
            """,
            question_id,
        )
    return True

