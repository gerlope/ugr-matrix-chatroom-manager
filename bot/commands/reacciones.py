USAGE = "!reacciones"
DESCRIPTION = "Muestra las reacciones dadas (profesores) o recibidas (alumnos)."

from core.db.constants import *
from core.db.modules import DB_MODULES
from config_bot import DB_TYPE

async def run(client, room_id, event, args):
    db = DB_MODULES[DB_TYPE]["queries"]

    mxid = event.sender
    user = await db.get_user_by_matrix_id(mxid)

    if not user:
        await client.send_text(room_id, "❌ No estás registrado en el sistema.")
        return

    texto = ""
    if user[COL_USER_IS_TEACHER]:
        reactions = await db.get_reacciones_por_profesor(mxid)
        if not reactions:
            texto = "❌ No has puesto ninguna reacción aún."
        else:
            texto = "❤️ Reacciones puestas:\n\n"
            last_course = None
            last_student = None
            for r in reactions:
                if last_course != r[COL_REACTION_ROOM_ID]:
                    if last_course is not None:
                        texto += "\n"
                    last_course = r[COL_REACTION_ROOM_ID]
                    texto += f"📚 Sala: {r[JOINED_REACTION_ROOM_SHORTCODE]}\n"
                    last_student = None
                if last_student != r[JOINED_REACTION_STUDENT_MATRIX_ID]:
                    if last_student is not None:
                        texto += "\n"
                    last_student = r[JOINED_REACTION_STUDENT_MATRIX_ID]
                    texto += f"    👤 Alumno: {r[JOINED_REACTION_STUDENT_MATRIX_ID]} (Moodle ID: {r[JOINED_REACTION_STUDENT_MOODLE_ID]})\n"
                reaction_date = r.get(COL_REACTION_DATE)
                date_text = reaction_date.strftime("%Y-%m-%d %H:%M:%S") if hasattr(reaction_date, "strftime") else str(reaction_date)
                message_text = (r.get(COL_REACTION_MESSAGE) or "").strip()
                texto += f"        • {r[COL_REACTION_EMOJI]} | {date_text}\n"
                if message_text:
                    texto += f"          {message_text}\n"
    else:
        reactions = await db.get_reacciones_por_estudiante(mxid)
        if not reactions:
            texto = "❌ No has recibido reacciones aún."
        else:
            texto = "❤️ Reacciones recibidas:\n\n"
            last_course = None
            last_teacher = None
            for r in reactions:
                if last_course != r[COL_REACTION_ROOM_ID]:
                    if last_course is not None:
                        texto += "\n"
                    last_course = r[COL_REACTION_ROOM_ID]
                    texto += f"📚 Sala: {r[JOINED_REACTION_ROOM_SHORTCODE]}\n"
                    last_teacher = None
                if last_teacher != r[JOINED_REACTION_TEACHER_MATRIX_ID]:
                    if last_teacher is not None:
                        texto += "\n"
                    last_teacher = r[JOINED_REACTION_TEACHER_MATRIX_ID]
                    texto += f"    👤 Profesor: {r[JOINED_REACTION_TEACHER_MATRIX_ID]}\n"
                reaction_date = r.get(COL_REACTION_DATE)
                date_text = reaction_date.strftime("%Y-%m-%d %H:%M:%S") if hasattr(reaction_date, "strftime") else str(reaction_date)
                message_text = (r.get(COL_REACTION_MESSAGE) or "").strip()
                texto += f"        • {r[COL_REACTION_EMOJI]} | {date_text}\n"
                if message_text:
                    texto += f"          {message_text}\n"

    await client.send_text(room_id, texto)
