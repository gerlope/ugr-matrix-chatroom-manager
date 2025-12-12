from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


class QueueState:
    FREE = "free"
    OCCUPIED = "occupied"


@dataclass
class QueueEntry:
    user_mxid: str
    notify_room_id: str
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RoomQueue:
    room_id: str
    teacher_mxid: str
    teacher_label: str
    teacher_localpart: str
    entries: List[QueueEntry] = field(default_factory=list)
    state: str = QueueState.FREE
    pending_user: Optional[str] = None
    pending_task: Optional[asyncio.Task] = None
    active_user: Optional[str] = None


class TutoringQueueManager:
    def __init__(self, confirmation_timeout: int = 60):
        self._queues: Dict[str, RoomQueue] = {}
        self._lock = asyncio.Lock()
        self._client = None
        self._confirmation_timeout = confirmation_timeout

    def configure_client(self, client) -> None:
        self._client = client

    async def enqueue(
        self,
        *,
        room_id: str,
        teacher_mxid: str,
        teacher_label: str,
        teacher_localpart: str,
        user_mxid: str,
        notify_room_id: str,
    ) -> Tuple[int, bool]:
        async with self._lock:
            queue = self._queues.get(room_id)
            if not queue:
                queue = RoomQueue(
                    room_id=room_id,
                    teacher_mxid=teacher_mxid,
                    teacher_label=teacher_label,
                    teacher_localpart=teacher_localpart,
                )
                self._queues[room_id] = queue
            else:
                queue.teacher_label = teacher_label or queue.teacher_label
                queue.teacher_localpart = teacher_localpart or queue.teacher_localpart
                queue.teacher_mxid = teacher_mxid or queue.teacher_mxid

            for idx, entry in enumerate(queue.entries):
                if entry.user_mxid == user_mxid:
                    position = idx + 1
                    return position, False

            queue.entries.append(QueueEntry(user_mxid=user_mxid, notify_room_id=notify_room_id))
            position = len(queue.entries)
            should_notify = (
                queue.state == QueueState.FREE
                and not queue.pending_user
                and position == 1
            )

        if should_notify:
            await self._notify_next(room_id)
        return position, True

    async def confirm_access(self, room_id: str, user_mxid: str) -> Tuple[bool, str]:
        async with self._lock:
            queue = self._queues.get(room_id)
            if not queue or queue.pending_user != user_mxid:
                return False, "No estás al frente de la cola o no tienes una invitación activa."

            queue.state = QueueState.OCCUPIED
            queue.active_user = user_mxid
            queue.pending_user = None
            pending_task = queue.pending_task
            queue.pending_task = None

        if pending_task:
            pending_task.cancel()
        return True, "Acceso confirmado. ¡Aprovecha tu tutoría!"

    async def release_current(self, room_id: str) -> Tuple[bool, Optional[str]]:
        async with self._lock:
            queue = self._queues.get(room_id)
            if not queue:
                return False, "No existe una cola para esta sala."

            removed_user = None
            pending_task = queue.pending_task
            if queue.entries:
                removed_user = queue.entries.pop(0).user_mxid
            queue.active_user = None
            queue.pending_user = None
            queue.pending_task = None
            queue.state = QueueState.FREE
            notify_next = bool(queue.entries)
            self._maybe_cleanup_locked(room_id)

        if pending_task:
            pending_task.cancel()
        if notify_next:
            await self._notify_next(room_id)
        return True, removed_user

    async def leave_queue(self, room_id: str, user_mxid: str) -> bool:
        async with self._lock:
            queue = self._queues.get(room_id)
            if not queue:
                return False

            removed = False
            pending_task = None
            for idx, entry in enumerate(list(queue.entries)):
                if entry.user_mxid != user_mxid:
                    continue
                removed = True
                queue.entries.pop(idx)
                if queue.pending_user == user_mxid:
                    pending_task = queue.pending_task
                    queue.pending_user = None
                    queue.pending_task = None
                if queue.active_user == user_mxid:
                    queue.active_user = None
                    queue.state = QueueState.FREE
                break

            notify_next = (
                removed
                and queue.state == QueueState.FREE
                and not queue.pending_user
                and bool(queue.entries)
            )
            self._maybe_cleanup_locked(room_id)

        if pending_task:
            pending_task.cancel()
        if notify_next:
            await self._notify_next(room_id)
        return removed

    async def handle_room_leave(self, room_id: str, user_mxid: str) -> bool:
        """Release the active slot when the attendee leaves the tutoring room."""
        async with self._lock:
            queue = self._queues.get(room_id)
            if not queue or queue.active_user != user_mxid:
                return False

            pending_task = queue.pending_task
            queue.pending_task = None
            queue.pending_user = None
            if queue.entries and queue.entries[0].user_mxid == user_mxid:
                queue.entries.pop(0)
            queue.active_user = None
            queue.state = QueueState.FREE
            notify_next = bool(queue.entries)
            self._maybe_cleanup_locked(room_id)

        if pending_task:
            pending_task.cancel()
        if notify_next:
            await self._notify_next(room_id)
        return True

    async def get_snapshot(self, room_id: str) -> Dict[str, object]:
        async with self._lock:
            queue = self._queues.get(room_id)
            if not queue:
                return {"state": QueueState.FREE, "entries": []}

            entries = []
            for idx, entry in enumerate(queue.entries):
                status = "waiting"
                if queue.pending_user == entry.user_mxid:
                    status = "awaiting-confirmation"
                if queue.active_user == entry.user_mxid:
                    status = "active"
                entries.append(
                    {
                        "position": idx + 1,
                        "user_mxid": entry.user_mxid,
                        "status": status,
                        "requested_at": entry.requested_at,
                    }
                )
            return {"state": queue.state, "entries": entries}

    async def is_active_user(self, room_id: str, user_mxid: str) -> bool:
        async with self._lock:
            queue = self._queues.get(room_id)
            if not queue:
                return False
            return queue.active_user == user_mxid

    async def _notify_next(self, room_id: str) -> None:
        entry_info: Optional[Tuple[QueueEntry, RoomQueue]] = None
        async with self._lock:
            queue = self._queues.get(room_id)
            if not queue or queue.state != QueueState.FREE or not queue.entries:
                return
            entry = queue.entries[0]
            if queue.pending_user == entry.user_mxid or queue.active_user == entry.user_mxid:
                return
            queue.pending_user = entry.user_mxid
            entry_info = (entry, queue)
            queue.pending_task = asyncio.create_task(
                self._handle_timeout(room_id, entry.user_mxid, entry.notify_room_id)
            )

        if not entry_info:
            return
        entry, queue = entry_info
        await self._safe_send(
            entry.notify_room_id,
            (
                f"👋 {entry.user_mxid}, la sala de tutoría de {queue.teacher_label} está libre. "
                f"Responde con `!tutoria confirmar {queue.teacher_localpart}` en el próximo minuto para mantener tu turno."
            ),
        )

    async def _handle_timeout(self, room_id: str, user_mxid: str, notify_room_id: str) -> None:
        try:
            await asyncio.sleep(self._confirmation_timeout)
            notify_next = False
            async with self._lock:
                queue = self._queues.get(room_id)
                if not queue or queue.pending_user != user_mxid:
                    return
                if queue.entries and queue.entries[0].user_mxid == user_mxid:
                    queue.entries.pop(0)
                queue.pending_user = None
                queue.pending_task = None
                queue.active_user = None
                queue.state = QueueState.FREE
                notify_next = bool(queue.entries)
                self._maybe_cleanup_locked(room_id)
            await self._safe_send(
                notify_room_id,
                "⏱️ Tiempo agotado. Pasamos al siguiente en la cola.",
            )
            if notify_next:
                await self._notify_next(room_id)
        except asyncio.CancelledError:
            return

    async def _safe_send(self, room_id: str, message: str) -> None:
        if not self._client:
            return
        try:
            await self._client.send_text(room_id, message)
        except Exception as exc:
            print(f"[WARN] No se pudo enviar mensaje de cola a {room_id}: {exc}")

    def _maybe_cleanup_locked(self, room_id: str) -> None:
        queue = self._queues.get(room_id)
        if not queue:
            return
        if not queue.entries and not queue.pending_user and not queue.active_user:
            if queue.pending_task:
                queue.pending_task.cancel()
            self._queues.pop(room_id, None)


tutoring_queue = TutoringQueueManager()
