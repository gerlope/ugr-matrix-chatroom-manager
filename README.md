# 🤖 UGR Matrix Bot

## AVISO: EN DESARROLLO, AUN NO ES FUNCIONAL

![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-GPLv3-red.svg)
![Matrix](https://img.shields.io/badge/platform-Matrix-FF69B4.svg)

**Autor:** Germán López Pérez  
**Biblioteca principal:** [mautrix-python](https://github.com/mautrix/python)

---

## 🎯 Descripción

**UGR Matrix Bot** es un bot diseñado para integrarse en el ecosistema **Matrix** y asistir en tareas de **ayuda a la docencia universitaria**.  
Puede responder a comandos personalizados, reaccionar ante mensajes, gestionar bienvenidas/despedidas de usuarios y procesar reacciones emoji en las salas.

Este bot fue desarrollado como parte de un **Trabajo Fin de Grado (TFG)** en la **Universidad de Granada**, dentro del área de informática y tecnologías colaborativas.

---

## 🧱 Estructura del proyecto

```folder_diagram
ugr-matrix-bot/
│
├── .gitgnore
├── LICENSE
├── README.md
├── bot.py
├── bot/
│   ├── config_bot.py
│   └── config_bot.py.example
├── web_dashboard/
│   ├── config_web.py
│   └── config_web.py.example
├── requirements.txt
│
├── core/
|   ├── db/
|   |   ├── postgres/
|   |   |   ├── conn.py
|   |   |   ├── queries.py
|   |   |   ├── schema.py
|   |   |   └── utils.py
|   |   └── constants.py
|   |
│   ├── client_manager.py
│   ├── command_registry.py
│   ├── event_router.py
│   ├── state_keys.py
│   └── state_manager.py
│
├── commands/
│   ├── ejemplo.py
│   └── ejemplo2.py
│
└── handlers/
    ├── messages.py
    ├── members.py
    ├── reactions.py
    └── redactions.py
```

Los archivos raíz `config_bot.py` y `config_web.py` se conservan solo como shims de compatibilidad.

---

## ⚙️ Instalación y configuración

### 1️⃣ Requisitos previos

- **Python 3.10+**
- Acceso a un servidor **Matrix**
- Un usuario o bot creado en Matrix (por ejemplo, `@bot:example.org`)
- **PostgreSQL 13+** instalado y en ejecución

### 2️⃣ Instalación de dependencias

Clona el repositorio y entra en la carpeta del proyecto:

```bash
git clone https://github.com/gerlope/ugr-matrix-bot.git
cd ugr-matrix-bot
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

Renombra y edita los archivos `bot/config_bot.py` y `web_dashboard/config_web.py` con los datos de tu instancia Matrix y base de datos:

```python
HOMESERVER = "https://matrix.example.org"
USERNAME = "@bot:example.org"
PASSWORD = "secret_password"
COMMAND_PREFIX = "!"


DB_TYPE = "postgres"  # Solo soporta "postgres" pero es útil para potenciales expansiones

DB_USER = "tu_usuario"
DB_PASSWORD = "tu_password"
DB_NAME = "matrix_bot"
DB_HOST = "localhost"
DB_PORT = 5432
```

### 5️⃣ Inicialización del esquema de la base de datos

La estructura de las tablas se encuentra en core/db/schema.sql.
Este archivo se ejecuta automáticamente al iniciar el bot por primera vez, creando las tablas necesarias.

Si deseas crear el esquema manualmente, puedes hacerlo con:

```bash
psql -U bot_user -d matrix_bot -f core/db/schema.sql
```

---

## ▶️ Ejecución

Ejecuta el bot con:

```bash
python bot.py
```

El bot se conectará a tu servidor Matrix y comenzará a escuchar eventos en las salas donde esté presente.

---

## 💬 Comandos disponibles

| Comando | Descripción |
|----------|--------------|
| `!ejemplo` | Ejemplo |
| `!ejemplo2` | Ejemplo 2 |

Puedes añadir fácilmente nuevos comandos creando archivos `.py` dentro de la carpeta `commands/`.

---

## 🧍‍♂️ Handlers incluidos

| Handler | Evento | Descripción |
|----------|--------|-------------|
| `messages.py` | `ROOM_MESSAGE` | Procesa mensajes y ejecuta comandos. |
| `members.py` | `ROOM_MEMBER` | Gestiona uniones, salidas e invitaciones a salas. |
| `reactions.py` | `REACTION` | Responde a reacciones emoji en mensajes. |

---

## 🧩 Extender el bot

Para crear un nuevo comando:

1. Añade un archivo en `commands/`, por ejemplo `commands/horario.py`
2. Define la función `run()`:

   ```python
   async def run(client, room_id, event):
       await client.send_text(room_id, "🗓️ Próxima clase: lunes 10:00, aula 203.")
   ```

3. Reinicia el bot.  
   ¡El nuevo comando se cargará automáticamente!

---

## 🧠 Objetivos del TFG

- Desarrollar un **asistente docente automatizado** basado en Matrix.
- Explorar la **arquitectura modular** para bots educativos.
- Facilitar la integración con sistemas docentes o LMS.
- Fomentar la participación y comunicación en entornos académicos distribuidos.
