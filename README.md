# 🤖 UGR Matrix Chatroom Manager

## ⚠️ Aviso importante

El inicio de sesión del panel web es un marcador de posición temporal. Debe sustituirse por una verificación externa de la universidad, por ejemplo SAML, antes de usarlo en producción.

Aparte la creación de usuarios en su servidor de Matrix y la creacion de las salas base de cada asignatura (y su registro de ellas en el sistema) deben ser realizadas aparte, hay un script de ejemplo y para tests llamado setup_example.py.

![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-GPLv3-red.svg)
![Matrix](https://img.shields.io/badge/platform-Matrix-FF69B4.svg)

**Autor:** Germán López Pérez
---

## 🎯 Descripción

**UGR Matrix Chatroom Manager** es un sistema de gestión para el ecosistema **Matrix** orientado a la **ayuda a la docencia universitaria**. Incluye un bot que automatiza la interacción en las salas y un dashboard web para administrar y consultar la información del sistema por parte de los docentes.

El bot puede responder a comandos personalizados, reaccionar ante mensajes, gestionar tutorias y procesar reacciones emoji en las salas, mientras que el panel web centraliza la gestión desde una interfaz Django.

Este sistema fue desarrollado como parte de un **Trabajo Fin de Grado (TFG)** en la **Universidad de Granada**, dentro del área de informática y tecnologías colaborativas.

---

## 🧱 Estructura del proyecto

El proyecto se organiza en dos partes principales:

- `bot/`: código del bot Matrix, sus comandos, handlers y configuración propia.
- `web_dashboard/`: aplicación Django del panel web, con su configuración y plantillas.

La configuración vive en archivos separados:

- `bot/config_bot.py` para el bot Matrix.
- `web_dashboard/config_web.py` para el panel web.

---

## ⚙️ Instalación y configuración

### 1️⃣ Requisitos previos

- **Python 3.10+**
- Acceso a un servidor **Matrix**
- Un usuario o bot creado en Matrix (por ejemplo, `@bot:example.org`)
    - Se recomienda que se le de excepciones a ratelimiting si su servidor matrix lo soporta.
- **PostgreSQL 13+** instalado y en ejecución

### 2️⃣ Instalación de dependencias

Clona el repositorio y entra en la carpeta del proyecto:

```bash
git clone https://github.com/gerlope/ugr-matrix-chatroom-manager.git
cd ugr-matrix-chatroom-manager
```

Instala las dependencias:

```bash
pip install -r requirements.txt
```

### 3️⃣ Creación de la base de datos PostgreSQL

Antes de iniciar el bot, asegúrate de crear la base de datos y el usuario de PostgreSQL:

```bash
sudo -u postgres psql
```

Dentro del shell de PostgreSQL, ejecuta:

```bash
CREATE DATABASE matrix_bot;
CREATE USER bot_user WITH PASSWORD 'bot_password';
GRANT ALL PRIVILEGES ON DATABASE matrix_bot TO bot_user;
```

💡 Nota: Usa otros nombres o contraseñas, pero asegúrate de reflejarlos en bot/config_bot.py y web_dashboard/config_web.py.

Luego, sal del shell con \q.

### 4️⃣ Configuración del bot

Edita `bot/config_bot.py` con los datos de tu instancia Matrix, Moodle y PostgreSQL:

```python
HOMESERVER = "https://matrix.example.org"
SERVER_NAME = "example.org"
USERNAME = "@bot:example.org"
PASSWORD = "secret_password"
COMMAND_PREFIX = "!"

DB_TYPE = "postgres"

DB_USER = "tu_usuario"
DB_PASSWORD = "tu_password"
DB_NAME = "matrix_bot"
DB_HOST = "localhost"
DB_PORT = 5432

MOODLE_URL = "https://moodle.example.com"
MOODLE_TOKEN = "TU_TOKEN_MOODLE"
```

### 5️⃣ Configuración del panel web

Edita `web_dashboard/config_web.py` con los datos del panel Django y la conexión compartida:

```python
HOMESERVER = "https://matrix.example.org"
SERVER_NAME = "example.org"
USERNAME = "@bot:example.org"
PASSWORD = "secret_password"

DJANGO_SECRET_KEY = "TU_SECRET_KEY"

DB_USER = "tu_usuario"
DB_PASSWORD = "tu_password"
DB_NAME = "matrix_bot"
DB_HOST = "localhost"
DB_PORT = 5432

MOODLE_URL = "https://moodle.example.com"
MOODLE_TOKEN = "TU_TOKEN_MOODLE"
```

### 6️⃣ Inicialización del esquema de la base de datos

La estructura de las tablas se encuentra en core/db/schema.sql.
Este archivo se ejecuta automáticamente al iniciar el bot por primera vez, creando las tablas necesarias.

Si deseas crear el esquema manualmente, puedes hacerlo con:

```bash
psql -U bot_user -d matrix_bot -f bot/core/db/postgres/schema.sql
```

---

## ▶️ Ejecución

Ejecuta el bot con:

```bash
python bot/main.py
```

El bot se conectará a tu servidor Matrix y comenzará a escuchar eventos en las salas donde esté presente.

## 🌐 Panel web

El dashboard está implementado como una aplicación Django estándar, así que puede desplegarse con el mismo flujo habitual de Django. La diferencia importante es que el login incluido en el proyecto es solo un marcador de posición y debe sustituirse por un sistema de autenticación externa de la universidad, por ejemplo SAML, antes de usarlo en producción.

Para arrancarlo en desarrollo:

```bash
python web_dashboard/manage.py runserver
```

Para ejecutar la suite de tests del dashboard:

```bash
python web_dashboard/manage.py test dashboard
```

---

## 💬 Comandos disponibles

| Comando | Descripción |
|----------|--------------|
| `!ayuda` | Muestra esta lista de comandos disponibles. |
| `!ping` | Comprueba si el bot está activo. |
| `!preguntas [todas]` | Muestra las preguntas activas de tus cursos. Usa `todas` para ver también las inactivas. |
| `!profesores` | Lista tus profesores con sus salas y datos de tutoria. |
| `!reacciones` | Muestra las reacciones dadas (profesores) o recibidas (alumnos). |
| `!reinvitar` | Te invita a las salas generales de tus cursos de Moodle y muestra enlaces. |
| `!responder <id_pregunta> <respuesta>` | Responde a una pregunta activa. Para preguntas de selección múltiple, separa las opciones con espacios. |
| `!respuestas <id_pregunta>` | Muestra tus respuestas a una pregunta específica. |
| `!tutoria [confirmar\|acabar\|salir\|estado] <profesor>` | Gestiona tutorías individuales. Encuentra <profesor> en el comando `!profesores`. |

Puedes añadir fácilmente nuevos comandos creando archivos `.py` dentro de la carpeta `commands/`.

---

## 🧩 Extender el bot

Para crear un nuevo comando:

1. Añade un archivo en `commands/`, por ejemplo `commands/horario.py`
2. Define las constantes `USAGE` y `DESCRIPTION` para que `!ayuda` lo incluya automáticamente.
3. Define la función `run()`:

   ```python
   USAGE = "!horario"
   DESCRIPTION = "Muestra el horario del grupo actual."

   async def run(client, room_id, event):
       await client.send_text(room_id, "🗓️ Próxima clase: lunes 10:00, aula 203.")
   ```

4. Reinicia el bot.  
   ¡El nuevo comando se cargará automáticamente!

---

## 🧠 Objetivos del TFG

- Desarrollar un **asistente docente automatizado** basado en Matrix.
- Explorar la **arquitectura modular** para bots educativos.
- Facilitar la integración con sistemas docentes o LMS.
- Fomentar la participación y comunicación en entornos académicos distribuidos.
