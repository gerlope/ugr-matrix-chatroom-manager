# core/db/modules.py
from core.db.postgres import conn as pg_conn, queries as pg_queries
DB_MODULES = {
        "postgres": {"conn": pg_conn, "queries": pg_queries},
    }

