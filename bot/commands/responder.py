# commands/responder.py
"""
Comando para responder a una pregunta activa.
Evalúa la respuesta según el tipo de pregunta y almacena el resultado.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from config import DB_TYPE
from core.db.constants import (
    COL_USER_MOODLE_ID,
    COL_USER_ID,
    get_db_modules,
)
from core.moodle import fetch_user_courses, fetch_user_groups_in_course

USAGE = "!responder <id_pregunta> <respuesta>|<opciones separadas por espacios>"
DESCRIPTION = "Responde a una pregunta activa. Para preguntas de selección múltiple, separa las opciones con espacios."


def _normalize_answer(answer: str) -> str:
    """Normaliza una respuesta para comparación."""
    return answer.strip().lower()


def _check_numeric_answer(given: str, expected: str, tolerance: float = 0.01) -> bool:
    """Compara respuestas numéricas con tolerancia."""
    try:
        given_num = float(given.replace(",", "."))
        expected_num = float(expected.replace(",", "."))
        return abs(given_num - expected_num) <= tolerance
    except (ValueError, TypeError):
        return False


async def run(client, room_id, event, args):
    db = get_db_modules()[DB_TYPE]["queries"]

    if len(args) < 2:
        await client.send_text(room_id, f"⚠️ Uso: {USAGE}")
        return

    # Parse question ID
    try:
        question_id = int(args[0])
    except ValueError:
        await client.send_text(room_id, "❌ El ID de la pregunta debe ser un número.")
        return

    # Get the answer (rest of the args)
    answer_parts = args[1:]
    answer_text = " ".join(answer_parts)

    # Get user info
    user_row = await db.get_user_by_matrix_id(event.sender)
    if not user_row:
        await client.send_text(room_id, "❌ No estás registrado en la base de datos.")
        return

    student_db_id = user_row[COL_USER_ID]
    user_moodle_id = user_row[COL_USER_MOODLE_ID]
    
    try:
        moodle_user_id = int(user_moodle_id)
    except (TypeError, ValueError):
        await client.send_text(room_id, "❌ Tu registro no tiene un Moodle ID válido.")
        return

    # Get question details
    question = await db.get_question_by_id(question_id)
    if not question:
        await client.send_text(room_id, f"❌ No se encontró la pregunta #{question_id}.")
        return

    question = dict(question)
    qtype = question.get("qtype", "")
    title = question.get("title") or f"Pregunta #{question_id}"
    allow_multiple_submissions = question.get("allow_multiple_submissions", False)
    allow_multiple_selections = question.get("allow_multiple_selections", False)
    close_on_first_correct = question.get("close_on_first_correct", False)
    close_triggered = question.get("close_triggered", False)
    allow_late = question.get("allow_late", False)
    expected_answer = question.get("expected_answer")
    start_at = question.get("start_at")
    end_at = question.get("end_at")
    manual_active = question.get("manual_active", False)
    room_course_id = question.get("room_course_id")
    room_moodle_group = question.get("room_moodle_group")

    # Check if question is closed
    if close_triggered:
        await client.send_text(room_id, f"❌ La pregunta #{question_id} ya está cerrada.")
        return

    # Check if question is active
    now = datetime.now(timezone.utc)
    is_active = False
    is_late = False
    
    if manual_active:
        is_active = True
    elif start_at and start_at <= now:
        if end_at is None or end_at >= now:
            is_active = True
        elif end_at < now:
            # Past end time - check if late submissions are allowed
            if allow_late:
                is_late = True
            else:
                await client.send_text(room_id, f"❌ La pregunta #{question_id} ya ha cerrado y no permite entregas tardías.")
                return
    elif start_at is None and end_at and end_at >= now:
        is_active = True
    elif start_at is None and end_at and end_at < now:
        if allow_late:
            is_late = True
        else:
            await client.send_text(room_id, f"❌ La pregunta #{question_id} ya ha cerrado y no permite entregas tardías.")
            return
    
    if not is_active and not is_late:
        await client.send_text(room_id, f"❌ La pregunta #{question_id} no está activa en este momento.")
        return

    # Check if user is enrolled in the course
    if room_course_id:
        courses = await fetch_user_courses(moodle_user_id)
        course_ids = [c.get("id") for c in courses if c.get("id")]
        if room_course_id not in course_ids:
            await client.send_text(room_id, "❌ No estás matriculado en el curso de esta pregunta.")
            return

        # Check group membership if applicable
        if room_moodle_group:
            user_groups = await fetch_user_groups_in_course(room_course_id, moodle_user_id)
            if room_moodle_group not in user_groups:
                await client.send_text(room_id, "❌ No perteneces al grupo de esta pregunta.")
                return

    # Check if user already answered (if multiple submissions not allowed)
    response_info = await db.get_student_response_count(question_id, student_db_id)
    response_count = response_info.get("count", 0) if response_info else 0
    max_version = response_info.get("max_version", 0) if response_info else 0
    
    if response_count > 0 and not allow_multiple_submissions:
        await client.send_text(
            room_id,
            f"❌ Ya has respondido a la pregunta #{question_id} y no se permiten múltiples envíos."
        )
        return

    new_version = (max_version or 0) + 1

    # Get options for this question
    options = await db.get_question_options(question_id)
    options_by_key = {opt["option_key"].upper(): opt for opt in options} if options else {}
    correct_option_ids = [opt["id"] for opt in options if opt.get("is_correct")] if options else []
    correct_option_keys = [opt["option_key"].upper() for opt in options if opt.get("is_correct")] if options else []

    # Evaluate the answer based on question type
    score = None
    is_graded = False
    selected_option_ids = []
    # For option-based questions, answer_text should be None (we use response_options table)
    # Only text-based questions (essay, short_answer, numeric) should store answer_text
    stored_answer = None

    if qtype == "essay":
        # Essay: no automatic grading, store the text
        is_graded = False
        score = None
        stored_answer = answer_text

    elif qtype == "poll":
        # Poll: no scoring, just record the selection
        is_graded = False
        score = None
        if options:
            given_keys = [k.upper() for k in answer_parts]
            for key in given_keys:
                if key in options_by_key:
                    selected_option_ids.append(options_by_key[key]["id"])
            if not selected_option_ids:
                await client.send_text(
                    room_id,
                    f"❌ Opción(es) no válida(s). Opciones disponibles: {', '.join(options_by_key.keys())}"
                )
                return

    elif qtype in ("multiple_choice", "true_false"):
        # Multiple choice / True-False: compare with correct options
        is_graded = True
        given_keys = [k.upper() for k in answer_parts]
        
        # Validate all given keys exist
        invalid_keys = [k for k in given_keys if k not in options_by_key]
        if invalid_keys:
            await client.send_text(
                room_id,
                f"❌ Opción(es) no válida(s): {', '.join(invalid_keys)}. Opciones disponibles: {', '.join(options_by_key.keys())}"
            )
            return
        
        # Get selected option IDs
        for key in given_keys:
            if key in options_by_key:
                selected_option_ids.append(options_by_key[key]["id"])
        
        if not selected_option_ids:
            await client.send_text(room_id, "❌ Debes seleccionar al menos una opción.")
            return
        
        # Check for multiple selection
        if len(given_keys) > 1 and not allow_multiple_selections:
            await client.send_text(
                room_id,
                "❌ Esta pregunta solo permite seleccionar una opción."
            )
            return
        
        # Calculate score
        if allow_multiple_selections:
            # For multi-select: partial credit based on correct/incorrect selections
            correct_selected = set(selected_option_ids) & set(correct_option_ids)
            incorrect_selected = set(selected_option_ids) - set(correct_option_ids)
            missed_correct = set(correct_option_ids) - set(selected_option_ids)
            
            if len(correct_option_ids) > 0:
                # Score = (correct selections - incorrect selections) / total correct options
                raw_score = (len(correct_selected) - len(incorrect_selected)) / len(correct_option_ids)
                score = max(0, min(1, raw_score)) * 100  # 0-100 scale
            else:
                score = 100 if not incorrect_selected else 0
        else:
            # Single selection: 100 if correct, 0 if not
            if selected_option_ids and selected_option_ids[0] in correct_option_ids:
                score = 100
            else:
                score = 0

    elif qtype == "short_answer":
        # Short answer: compare with expected_answer
        is_graded = True
        stored_answer = answer_text
        if expected_answer:
            if _normalize_answer(answer_text) == _normalize_answer(expected_answer):
                score = 100
            else:
                score = 0
        else:
            # No expected answer set - manual grading required
            is_graded = False

    elif qtype == "numeric":
        # Numeric: compare with expected_answer with tolerance
        is_graded = True
        stored_answer = answer_text
        if expected_answer:
            if _check_numeric_answer(answer_text, expected_answer):
                score = 100
            else:
                score = 0
        else:
            is_graded = False

    else:
        # Unknown type - just store
        is_graded = False

    # Insert the response
    first_option_id = selected_option_ids[0] if selected_option_ids and not allow_multiple_selections else None
    response_id = await db.insert_question_response(
        question_id=question_id,
        student_id=student_db_id,
        answer_text=stored_answer,
        option_id=first_option_id,
        score=score,
        is_graded=is_graded,
        response_version=new_version,
        late=is_late,
    )

    if not response_id:
        await client.send_text(room_id, "❌ Error al guardar la respuesta. Inténtalo de nuevo.")
        return

    # Insert multi-select options if applicable
    if allow_multiple_selections and len(selected_option_ids) > 1:
        await db.insert_response_options(response_id, selected_option_ids)

    # Check if we need to close the question (close_on_first_correct)
    if close_on_first_correct and score == 100:
        await db.set_question_close_triggered(question_id)

    # Build response message
    late_note = " (⚠️ Entrega tardía)" if is_late else ""
    attempt_note = f" (🔄 Intento #{new_version})" if allow_multiple_submissions and new_version > 1 else ""
    
    if qtype in ("essay", "poll"):
        result_msg = f"✅ Tu respuesta a '{title}' ha sido registrada.{attempt_note}{late_note}"
    elif is_graded and score is not None:
        score_emoji = "🎉" if score == 100 else "📊"
        result_msg = f"{score_emoji} Tu respuesta a '{title}' ha sido registrada.{attempt_note}{late_note}\n📈 Puntuación: {score:.0f}/100"
        if close_on_first_correct and score == 100:
            result_msg += "\n🏁 ¡Has cerrado la pregunta al ser el primero en acertar!"
    else:
        result_msg = f"✅ Tu respuesta a '{title}' ha sido registrada. Pendiente de calificación.{attempt_note}{late_note}"

    await client.send_text(room_id, result_msg)
