"""Helper functions to interact with Moodle REST endpoints."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import requests

from config import MOODLE_TOKEN, MOODLE_URL

MOODLE_TIMEOUT = 20
MOODLE_ENDPOINT = f"{MOODLE_URL.rstrip('/')}/webservice/rest/server.php"
TEACHER_ROLE_SHORTNAMES = {"editingteacher", "teacher"}


def _is_teacher(participant: Dict[str, Any]) -> bool:
    roles = participant.get("roles") or []
    for role in roles:
        shortname = str(role.get("shortname", "")).casefold()
        if shortname in TEACHER_ROLE_SHORTNAMES:
            return True
    return False


async def _moodle_request(params: Dict[str, Any], context: str) -> Optional[Any]:
    loop = asyncio.get_running_loop()

    def _do_request():
        response = requests.get(MOODLE_ENDPOINT, params=params, timeout=MOODLE_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data or []

    try:
        return await loop.run_in_executor(None, _do_request)
    except Exception as exc:
        print(f"[WARN] Error consultando Moodle ({context}): {exc}")
        return None


async def fetch_user_courses(moodle_user_id: int) -> List[Dict[str, Any]]:
    params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "core_enrol_get_users_courses",
        "moodlewsrestformat": "json",
        "userid": moodle_user_id,
    }
    payload = await _moodle_request(params, "core_enrol_get_users_courses")
    return payload if isinstance(payload, list) else []


async def fetch_course_participants(course_id: int) -> List[Dict[str, Any]]:
    params = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "core_enrol_get_enrolled_users",
        "moodlewsrestformat": "json",
        "courseid": course_id,
    }
    payload = await _moodle_request(params, "core_enrol_get_enrolled_users")
    return payload if isinstance(payload, list) else []


async def fetch_course_teachers(course_id: int) -> List[Dict[str, Any]]:
    participants = await fetch_course_participants(course_id)
    return [p for p in participants if _is_teacher(p)]
