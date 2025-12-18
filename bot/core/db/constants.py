# core/db/constants.py

# Import modules lazily to avoid circular imports
def _get_db_modules():
    from core.db.postgres import conn as pg_conn, queries as pg_queries
    return {
        "postgres": {"conn": pg_conn, "queries": pg_queries},
    }

DB_MODULES = None  # Will be initialized on first access

def get_db_modules():
    global DB_MODULES
    if DB_MODULES is None:
        DB_MODULES = _get_db_modules()
    return DB_MODULES

# Users
TABLE_USERS = "users"

COL_USER_ID = "id"
COL_USER_MATRIX_ID = "matrix_id"
COL_USER_MOODLE_ID = "moodle_id"
COL_USER_IS_TEACHER = "is_teacher"
COL_USER_REGISTERED_AT = "registered_at"

# Rooms
TABLE_ROOMS = "rooms"

COL_ROOM_ID = "id"
COL_ROOM_ROOM_ID = "room_id"
COL_ROOM_MOODLE_COURSE_ID = "moodle_course_id"
COL_ROOM_TEACHER_ID = "teacher_id"
COL_ROOM_SHORTCODE = "shortcode"
COL_ROOM_MOODLE_GROUP = "moodle_group"
COL_ROOM_CREATED_AT = "created_at"
COL_ROOM_ACTIVE = "active"

# Reactions
TABLE_REACTIONS = "reactions"

COL_REACTION_ID = "id"
COL_REACTION_TEACHER_ID = "teacher_id"
COL_REACTION_STUDENT_ID = "student_id"
COL_REACTION_ROOM_ID = "room_id"
COL_REACTION_EMOJI = "emoji"
COL_REACTION_COUNT = "count"
COL_REACTION_LAST_UPDATED = "last_updated"

JOINED_REACTION_TEACHER_MATRIX_ID = "teacher_matrix_id"
JOINED_REACTION_TEACHER_MOODLE_ID = "teacher_moodle_id"
JOINED_REACTION_STUDENT_MATRIX_ID = "student_matrix_id"
JOINED_REACTION_STUDENT_MOODLE_ID = "student_moodle_id"
JOINED_REACTION_ROOM_SHORTCODE = "room_shortcode"
JOINED_REACTION_ROOM_MOODLE_COURSE_ID = "room_moodle_course_id"

# Teacher Availability
TABLE_TEACHER_AVAILABILITY = "teacher_availability"

COL_TEACHER_AVAILABILITY_ID = "id"
COL_TEACHER_AVAILABILITY_TEACHER_ID = "teacher_id"
COL_TEACHER_AVAILABILITY_DAY_OF_WEEK = "day_of_week"
COL_TEACHER_AVAILABILITY_START_TIME = "start_time"
COL_TEACHER_AVAILABILITY_END_TIME = "end_time"

# Questions
TABLE_QUESTIONS = "questions"

COL_QUESTION_ID = "id"
COL_QUESTION_TEACHER_ID = "teacher_id"
COL_QUESTION_ROOM_ID = "room_id"
COL_QUESTION_TITLE = "title"
COL_QUESTION_BODY = "body"
COL_QUESTION_QTYPE = "qtype"
COL_QUESTION_START_AT = "start_at"
COL_QUESTION_END_AT = "end_at"
COL_QUESTION_MANUAL_ACTIVE = "manual_active"
COL_QUESTION_ALLOW_MULTIPLE_SUBMISSIONS = "allow_multiple_submissions"
COL_QUESTION_ALLOW_MULTIPLE_SELECTIONS = "allow_multiple_selections"
COL_QUESTION_CLOSE_ON_FIRST_CORRECT = "close_on_first_correct"
COL_QUESTION_CLOSE_TRIGGERED = "close_triggered"
COL_QUESTION_CREATED_AT = "created_at"

# Question Options
TABLE_QUESTION_OPTIONS = "question_options"

COL_QUESTION_OPTION_ID = "id"
COL_QUESTION_OPTION_QUESTION_ID = "question_id"
COL_QUESTION_OPTION_KEY = "option_key"
COL_QUESTION_OPTION_TEXT = "text"
COL_QUESTION_OPTION_IS_CORRECT = "is_correct"
COL_QUESTION_OPTION_POSITION = "position"
