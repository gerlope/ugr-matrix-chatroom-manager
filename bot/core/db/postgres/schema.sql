-- ============================================
-- PostgreSQL schema for UGR Matrix Bot
-- ============================================

-- Users table 
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    matrix_id TEXT UNIQUE NOT NULL,        -- Matrix user ID
    moodle_id INTEGER UNIQUE NOT NULL,     -- Moodle user ID
    is_teacher BOOLEAN DEFAULT FALSE,      -- true = teacher, false = student
    registered_at TIMESTAMP DEFAULT NOW()
);

-- 🔹 Index for fast lookup by Matrix ID
CREATE INDEX IF NOT EXISTS idx_users_matrix_id ON users(matrix_id);


-- Chat rooms table
CREATE TABLE IF NOT EXISTS rooms (
    id SERIAL PRIMARY KEY,
    room_id TEXT UNIQUE NOT NULL,          -- Actual Matrix room ID
    moodle_course_id INTEGER,              -- Moodle course ID (NULL for tutorías)
    teacher_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    shortcode TEXT NOT NULL,               -- short identifier used by the teacher
    moodle_group TEXT,                     -- optional Moodle group, if present only that group has access
    created_at TIMESTAMP DEFAULT NOW(),
    active BOOLEAN DEFAULT TRUE           -- whether the room is active
);

-- Ensure shortcode is unique per teacher only when the room is active
CREATE UNIQUE INDEX IF NOT EXISTS unique_active_shortcode_per_teacher
    ON rooms (teacher_id, shortcode)
    WHERE active = TRUE;

-- 🔹 Index for fast lookup by Matrix room ID
CREATE INDEX IF NOT EXISTS idx_rooms_room_id ON rooms(room_id);

-- 🔹 Index for quick lookup by (teacher, shortcode)
CREATE INDEX IF NOT EXISTS idx_rooms_teacher_shortcode ON rooms(teacher_id, shortcode);


-- Reactions table (teacher → student in a course)
CREATE TABLE IF NOT EXISTS reactions (
    id SERIAL PRIMARY KEY,
    teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    emoji TEXT NOT NULL,                   -- reaction emoji ("👍", etc.)
    count INTEGER DEFAULT 1 CHECK (count >= 1),
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE (teacher_id, student_id, room_id, emoji)
);

-- 🔹 Indexes for faster joins and lookups
CREATE INDEX IF NOT EXISTS idx_reactions_teacher_id ON reactions(teacher_id);
CREATE INDEX IF NOT EXISTS idx_reactions_student_id ON reactions(student_id);
CREATE INDEX IF NOT EXISTS idx_reactions_room_id ON reactions(room_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type WHERE typname = 'weekday'
    ) THEN
        CREATE TYPE weekday AS ENUM (
            'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'
        );
    END IF;
END
$$;

-- Teacher availability table
CREATE TABLE IF NOT EXISTS teacher_availability (
    id SERIAL PRIMARY KEY,
    teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day_of_week weekday NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    CONSTRAINT chk_time_valid CHECK (start_time < end_time)
    );

-- 🔹 Index for fast lookup by teacher ID
CREATE INDEX IF NOT EXISTS idx_teacher_availability_teacher_id ON teacher_availability(teacher_id);

-- 🔹 Trigger to prevent overlapping intervals for the same teacher (covers INSERT and UPDATE)
CREATE OR REPLACE FUNCTION trg_no_overlap_func()
RETURNS TRIGGER AS $$
BEGIN
    -- Exclude the row being updated (if any) using IS DISTINCT FROM so NULLs are handled
    IF EXISTS (
        SELECT 1
        FROM teacher_availability
        WHERE teacher_id = NEW.teacher_id
          AND day_of_week = NEW.day_of_week
          AND NEW.start_time < end_time
          AND NEW.end_time > start_time
          AND (id IS DISTINCT FROM NEW.id)
    ) THEN
        RAISE EXCEPTION 'Time interval overlaps with existing interval for this teacher';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_no_overlap'
    ) THEN
        CREATE TRIGGER trg_no_overlap
        BEFORE INSERT OR UPDATE ON teacher_availability
        FOR EACH ROW
        EXECUTE FUNCTION trg_no_overlap_func();
    END IF;
END
$$;

-- 🔹 Trigger to enforce availability time window (07:00 - 21:00)
-- This prevents storing availability that starts before 07:00 or ends after 21:00.
CREATE OR REPLACE FUNCTION trg_time_bounds_func()
RETURNS TRIGGER AS $$
BEGIN
    -- enforce inclusive lower bound at 07:00 and inclusive upper bound at 21:00
    -- (start_time must be >= 07:00, end_time must be <= 21:00)
    IF NEW.start_time < TIME '07:00' OR NEW.end_time > TIME '21:00' THEN
        RAISE EXCEPTION 'Availability must be within 07:00 and 21:00 (start=% / end=%)', NEW.start_time, NEW.end_time;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_time_bounds'
    ) THEN
        CREATE TRIGGER trg_time_bounds
        BEFORE INSERT OR UPDATE ON teacher_availability
        FOR EACH ROW
        EXECUTE FUNCTION trg_time_bounds_func();
    END IF;
END
$$;

-- ============================================
 
-- ============================================
-- Questions / Quiz feature
-- ============================================

-- Create an enum for question types (multiple choice, true/false, short answer, numeric, essay)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'question_type') THEN
        CREATE TYPE question_type AS ENUM (
            'multiple_choice',
            'poll',
            'true_false',
            'short_answer',
            'numeric',
            'essay'
        );
    END IF;
END
$$;

-- Questions table: metadata and availability window
CREATE TABLE IF NOT EXISTS questions (
    id SERIAL PRIMARY KEY,
    teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    room_id INTEGER NULL REFERENCES rooms(id) ON DELETE CASCADE,
    title TEXT,
    body TEXT NOT NULL,
    qtype question_type NOT NULL,
    expected_answer TEXT,
    start_at TIMESTAMP WITH TIME ZONE,
    end_at TIMESTAMP WITH TIME ZONE,
    manual_active BOOLEAN DEFAULT FALSE,
    allow_multiple_submissions BOOLEAN DEFAULT FALSE,
    allow_multiple_selections BOOLEAN DEFAULT FALSE,
    allow_late BOOLEAN DEFAULT FALSE,
    close_on_first_correct BOOLEAN DEFAULT FALSE,
    close_triggered BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_questions_room_start_end ON questions(room_id, start_at, end_at);

-- Options for questions (used for multiple choice / true-false)
CREATE TABLE IF NOT EXISTS question_options (
    id SERIAL PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    option_key TEXT NOT NULL,
    text TEXT NOT NULL,
    is_correct BOOLEAN DEFAULT FALSE,
    position INTEGER DEFAULT 0,
    UNIQUE (question_id, option_key)
);

CREATE INDEX IF NOT EXISTS idx_question_options_qid ON question_options(question_id);

-- Responses: one row per submission. Answers stored in answer_text for free-text; option selections stored in response_options (below).
CREATE TABLE IF NOT EXISTS question_responses (
    id SERIAL PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    option_id INTEGER NULL REFERENCES question_options(id) ON DELETE SET NULL,
    answer_text TEXT NULL,
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_graded BOOLEAN DEFAULT FALSE,
    score NUMERIC(6,2) NULL,
    grader_id INTEGER NULL REFERENCES users(id),
    feedback TEXT NULL,
    response_version INTEGER DEFAULT 1,
    late BOOLEAN DEFAULT FALSE,
    UNIQUE (question_id, student_id, response_version)
);

CREATE INDEX IF NOT EXISTS idx_responses_question_student ON question_responses(question_id, student_id);
CREATE INDEX IF NOT EXISTS idx_responses_question_submitted ON question_responses(question_id, submitted_at);

-- Mapping table to allow multiple selected options per response (for multi-select questions)
CREATE TABLE IF NOT EXISTS response_options (
    response_id INTEGER NOT NULL REFERENCES question_responses(id) ON DELETE CASCADE,
    option_id INTEGER NOT NULL REFERENCES question_options(id) ON DELETE CASCADE,
    PRIMARY KEY (response_id, option_id)
);

CREATE INDEX IF NOT EXISTS idx_response_options_option ON response_options(option_id);

-- ============================================