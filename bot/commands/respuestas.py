# commands/respuestas.py
"""
Muestra las respuestas del usuario a una pregunta específica.
"""
from __future__ import annotations

from datetime import datetime, timezone

from config import DB_TYPE
from core.db.constants import (
    COL_USER_ID,
    COL_QUESTION_TITLE,
    COL_QUESTION_QTYPE,
    COL_QUESTION_ALLOW_MULTIPLE_SUBMISSIONS,
    COL_QUESTION_START_AT,
    COL_QUESTION_END_AT,
    COL_QUESTION_MANUAL_ACTIVE,
    COL_QUESTION_CLOSE_TRIGGERED,
    COL_QUESTION_OPTION_ID,
    COL_QUESTION_OPTION_KEY,
    COL_QUESTION_OPTION_TEXT,
    COL_RESPONSE_ID,
    COL_RESPONSE_ANSWER_TEXT,
    COL_RESPONSE_OPTION_ID,
    COL_RESPONSE_SUBMITTED_AT,
    COL_RESPONSE_IS_GRADED,
    COL_RESPONSE_SCORE,
    COL_RESPONSE_GRADER_ID,
    COL_RESPONSE_FEEDBACK,
    COL_RESPONSE_VERSION,
    COL_RESPONSE_LATE,
    get_db_modules,
)

USAGE = "!respuestas <id_pregunta>"
DESCRIPTION = "Muestra tus respuestas a una pregunta específica."


def _is_question_active(question: dict) -> bool:
    """Determina si una pregunta está activa."""
    # If close_triggered, it's not active
    if question.get(COL_QUESTION_CLOSE_TRIGGERED):
        return False
    
    # If manual_active is True, it's active
    if question.get(COL_QUESTION_MANUAL_ACTIVE):
        return True
    
    now = datetime.now(timezone.utc)
    start_at = question.get(COL_QUESTION_START_AT)
    end_at = question.get(COL_QUESTION_END_AT)
    
    # Ensure timezone awareness
    if start_at and start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    if end_at and end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)
    
    # Check scheduled activation
    if start_at is not None:
        if start_at <= now and (end_at is None or end_at >= now):
            return True
    elif end_at is not None and end_at >= now:
        return True
    
    return False


async def run(client, room_id, event, args):
    db = get_db_modules()[DB_TYPE]["queries"]

    if len(args) < 1:
        await client.send_text(room_id, f"⚠️ Uso: {USAGE}")
        return

    # Parse question ID
    try:
        question_id = int(args[0])
    except ValueError:
        await client.send_text(room_id, "❌ El ID de la pregunta debe ser un número.")
        return

    # Get user info
    user_row = await db.get_user_by_matrix_id(event.sender)
    if not user_row:
        await client.send_text(room_id, "❌ No estás registrado en la base de datos.")
        return

    student_db_id = user_row[COL_USER_ID]

    # Get question info
    question = await db.get_question_by_id(question_id)
    if not question:
        await client.send_text(room_id, f"❌ No se encontró la pregunta #{question_id}.")
        return

    title = question.get(COL_QUESTION_TITLE) or f"Pregunta #{question_id}"
    qtype = question.get(COL_QUESTION_QTYPE) or "unknown"
    allow_multiple_submissions = question.get(COL_QUESTION_ALLOW_MULTIPLE_SUBMISSIONS, False)
    
    # Check if question is still active (scores hidden while active)
    question_is_active = _is_question_active(question)

    # Get student's responses
    responses = await db.get_student_responses_for_question(question_id, student_db_id)
    if not responses:
        await client.send_text(room_id, f"ℹ️ No tienes respuestas para la pregunta #{question_id} ({title}).")
        return

    # Get options for the question (if applicable)
    options = await db.get_question_options(question_id)
    options_by_id = {opt[COL_QUESTION_OPTION_ID]: opt for opt in options}

    # Determine max version for "is latest" marker
    max_version = max(r.get(COL_RESPONSE_VERSION, 1) for r in responses)

    # Build output
    lines = [f"📋 Tus respuestas a: #{question_id} │ {title}"]
    lines.append(f"   Tipo: {_get_qtype_label(qtype)}")
    if allow_multiple_submissions:
        lines.append("   🔁 Permite múltiples envíos")
    if question_is_active:
        lines.append("   🟢 Pregunta activa (puntuaciones ocultas)")
    lines.append("─" * 35)

    for r in responses:
        resp_id = r.get(COL_RESPONSE_ID)
        version = r.get(COL_RESPONSE_VERSION, 1)
        is_latest = version == max_version
        submitted_at = r.get(COL_RESPONSE_SUBMITTED_AT)
        answer_text = r.get(COL_RESPONSE_ANSWER_TEXT)
        option_id = r.get(COL_RESPONSE_OPTION_ID)
        is_graded = r.get(COL_RESPONSE_IS_GRADED, False)
        score = r.get(COL_RESPONSE_SCORE)
        late = r.get(COL_RESPONSE_LATE, False)
        feedback = r.get(COL_RESPONSE_FEEDBACK)
        grader_id = r.get(COL_RESPONSE_GRADER_ID)
        grader_matrix_id = r.get("grader_matrix_id")

        # Attempt header
        attempt_label = f"🔄 Intento #{version}"
        if is_latest and allow_multiple_submissions:
            attempt_label += " (✓ Última)"
        lines.append(f"\n{attempt_label}")

        # Submission time
        if submitted_at:
            try:
                if hasattr(submitted_at, "strftime"):
                    time_str = submitted_at.strftime("%Y-%m-%d %H:%M")
                else:
                    time_str = str(submitted_at)
                lines.append(f"   📅 Enviado: {time_str}")
            except Exception:
                lines.append(f"   📅 Enviado: {submitted_at}")

        # Late indicator
        if late:
            lines.append("   ⚠️ Entrega tardía")

        # Answer content
        if answer_text:
            lines.append(f"   📝 Respuesta: {answer_text}")
        
        # For option-based questions, get selected options
        if qtype in ("multiple_choice", "true_false", "poll"):
            response_option_ids = await db.get_response_option_ids(resp_id)
            if response_option_ids:
                selected_opts = []
                for opt_id in response_option_ids:
                    opt = options_by_id.get(opt_id)
                    if opt:
                        selected_opts.append(f"{opt.get(COL_QUESTION_OPTION_KEY, '?')}) {opt.get(COL_QUESTION_OPTION_TEXT, '')}")
                    else:
                        selected_opts.append(f"Opción ID {opt_id}")
                lines.append("   📝 Opciones seleccionadas:")
                for so in selected_opts:
                    lines.append(f"      • {so}")
            elif option_id:
                opt = options_by_id.get(option_id)
                if opt:
                    lines.append(f"   📝 Opción: {opt.get(COL_QUESTION_OPTION_KEY, '?')}) {opt.get(COL_QUESTION_OPTION_TEXT, '')}")
                else:
                    lines.append(f"   📝 Opción ID: {option_id}")

        # Score, grading source, and feedback are only shown when question is inactive
        if not question_is_active:
            # Score
            if is_graded and score is not None:
                score_emoji = "🎉" if score == 100 else ("📊" if score >= 50 else "📉")
                lines.append(f"   {score_emoji} Puntuación: {score:.0f}/100")
            elif not is_graded:
                lines.append("   ⏳ Pendiente de calificación")

            # Grading source
            if is_graded:
                if grader_id and grader_matrix_id:
                    lines.append(f"   👤 Corregido por: {grader_matrix_id}")
                else:
                    lines.append("   🤖 Corregido por: Automática")

            # Feedback
            if feedback:
                lines.append(f"   💬 Feedback: {feedback}")

    lines.append("\n" + "━" * 35)
    
    message = "\n".join(lines)
    await client.send_text(room_id, message)


def _get_qtype_label(qtype: str) -> str:
    """Returns a human-readable label for question type."""
    labels = {
        "multiple_choice": "📝 Test/Multiple selección",
        "poll": "📊 Encuesta",
        "true_false": "✅ Verdadero/Falso",
        "short_answer": "✍️ Respuesta corta",
        "numeric": "🔢 Numérico",
        "essay": "📄 Ensayo",
    }
    return labels.get(qtype, f"📌 {qtype}")
