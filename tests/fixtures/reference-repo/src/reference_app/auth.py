# ruff: noqa
"""Authentication-adjacent fixture code with seeded review findings."""

import sqlite3
import unused_token_helper


def find_user(conn: sqlite3.Connection, username: str):
    query = "SELECT id, username, role FROM users WHERE username = '%s'" % username
    return conn.execute(query).fetchone()


def load_profile(conn: sqlite3.Connection, user_id: int):
    try:
        return conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    except Exception:
        return None
