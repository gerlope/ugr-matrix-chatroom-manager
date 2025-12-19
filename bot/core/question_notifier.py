# core/question_notifier.py
"""
Background task that monitors questions for activation and sends room notifications.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional, Set

from mautrix.types import TextMessageEventContent, MessageType, Format

from core.db.constants import get_db_modules
from config import DB_TYPE


QTYPE_LABELS = {
    "multiple_choice": "📝 Test/Multiple selección",
    "poll": "📊 Encuesta",
    "true_false": "✅ Verdadero/Falso",
    "short_answer": "✍️ Respuesta corta",
    "numeric": "🔢 Numérico",
    "essay": "📄 Ensayo",
}


class QuestionNotifier:
    """
    Periodically checks for newly-active questions and alerts rooms.
    """

    def __init__(self, check_interval: int = 30):
        self._client = None
        self._check_interval = check_interval
        self._task: Optional[asyncio.Task] = None
        # Track questions we've already announced: question_id -> True
        self._announced: Set[int] = set()

    def configure_client(self, client) -> None:
        self._client = client

    def start(self) -> None:
        """Start the background polling task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._startup_and_poll())
            print("[QuestionNotifier] Background task started")

    def stop(self) -> None:
        """Stop the background polling task."""
        if self._task and not self._task.done():
            self._task.cancel()
            print("[QuestionNotifier] Background task stopped")

    async def _startup_and_poll(self) -> None:
        """Take initial snapshot then start polling."""
        try:
            await self._take_initial_snapshot()
        except Exception as exc:
            print(f"[QuestionNotifier] Error taking initial snapshot: {exc}")
        await self._poll_loop()

    async def _take_initial_snapshot(self) -> None:
        """Mark all currently active questions as already announced."""
        if not self._client:
            return

        db_queries = get_db_modules()[DB_TYPE]["queries"]
        active_questions = await db_queries.get_all_currently_active_questions()
        
        for q in active_questions:
            self._announced.add(q["id"])
        
        print(f"[QuestionNotifier] Initial snapshot: {len(self._announced)} questions already active")

    async def _poll_loop(self) -> None:
        """Main polling loop that checks for active questions."""
        while True:
            try:
                await self._check_active_questions()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"[QuestionNotifier] Error in poll loop: {exc}")
            await asyncio.sleep(self._check_interval)

    async def _check_active_questions(self) -> None:
        """Query for active questions and notify rooms for new ones."""
        if not self._client:
            return

        db_queries = get_db_modules()[DB_TYPE]["queries"]
        
        # Get all currently active questions across all rooms
        active_questions = await db_queries.get_all_currently_active_questions()
        
        for q in active_questions:
            question_id = q["id"]
            if question_id in self._announced:
                continue
            
            # Mark as announced before sending to avoid duplicates
            self._announced.add(question_id)
            
            room_matrix_id = q.get("room_matrix_id")
            if not room_matrix_id:
                continue
            
            title = q.get("title") or "Sin título"
            body = q.get("body", "")
            qtype = q.get("qtype", "")
            end_at = q.get("end_at")
            
            # Format qtype nicely
            qtype_label = QTYPE_LABELS.get(qtype, f"📌 {qtype}")
            
            # Build flags list
            flags = [qtype_label]
            if q.get("allow_multiple_selections"):
                flags.append("✅ Multiple selección")
            if q.get("allow_multiple_submissions"):
                flags.append("🔁 Permite múltiples envíos")
            if q.get("close_on_first_correct"):
                flags.append("🏁 Cierra al primer acierto")
            
            flags_text = " · ".join(flags)
            
            # Format end time if available
            end_info = ""
            if end_at:
                if isinstance(end_at, datetime):
                    end_info = f"\n ⏰ Cierra: {end_at.strftime('%d/%m/%Y %H:%M')}"
                else:
                    end_info = f"\n ⏰ Cierra: {end_at}"
            
            # Get options if this question has them
            options_text = ""
            try:
                options = await db_queries.get_question_options(question_id)
                if options:
                    options_lines = []
                    for opt in options:
                        key = opt.get("option_key", "")
                        text = opt.get("text", "")
                        options_lines.append(f"  {key}) {text}")
                    options_text = "\n" + "\n".join(options_lines)
            except Exception as exc:
                print(f"[QuestionNotifier] Failed to get options for question {question_id}: {exc}")
            
            # Build response instructions based on question type
            is_multiple_selection = q.get("allow_multiple_selections")
            if is_multiple_selection:
                response_hint = f"Responde con `!responder {question_id} <seleccion1> [<seleccion2> ...]` (claves separadas por espacios) en mensaje privado con {self._client.mxid}."
            elif qtype == "multiple_choice" or qtype == "true_false" or qtype == "poll":
                response_hint = f"Responde con `!responder {question_id} <selección>` en mensaje privado con {self._client.mxid}."
            else:
                response_hint = f"Responde con `!responder {question_id} <respuesta>` en mensaje privado con {self._client.mxid}."
            
            # Build the notification message with @room
            message = (
                f"@room 📣 ¡Nueva pregunta activa!\n\n"
                f"🔹 #{question_id} │ {title}\n"
                f"   {flags_text}"
                f"   {end_info}\n\n"
                f"{body}\n"
                f"{options_text}\n\n"
                f"{response_hint}"
            )
            
            try:
                await self._client.send_text(room_matrix_id, message)
                print(f"[QuestionNotifier] Announced question {question_id} in {room_matrix_id}")
            except Exception as exc:
                print(f"[QuestionNotifier] Failed to notify room {room_matrix_id} for question {question_id}: {exc}")
                # Remove from announced so we retry next time
                self._announced.discard(question_id)

    def clear_announced(self, question_id: int) -> None:
        """Remove a question from the announced set (e.g., if it was deactivated)."""
        self._announced.discard(question_id)


# Singleton instance
question_notifier = QuestionNotifier()
