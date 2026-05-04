from __future__ import annotations
import sqlite3
import threading
import time


class Database:
    """
    In-memory SQLite key-value store.
    access_count tracks every round-trip to the DB (reads + writes).
    """

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._lock = threading.Lock()
        self.access_count: int = 0
        self._conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT, updated_at REAL)"
        )
        self._conn.commit()

    def seed(self, n: int = 100) -> None:
        """Pre-populate the DB with n rows so every key already exists."""
        ts = time.time()
        with self._lock:
            self._conn.executemany(
                "INSERT INTO items VALUES (?,?,?)",
                [(i, f"value_{i}", ts) for i in range(n)],
            )
            self._conn.commit()

    def read(self, key: int) -> str | None:
        with self._lock:
            self.access_count += 1
            row = self._conn.execute(
                "SELECT value FROM items WHERE id=?", (key,)
            ).fetchone()
        return row[0] if row else None

    def write(self, key: int, value: str) -> None:
        with self._lock:
            self.access_count += 1
            self._conn.execute(
                "INSERT OR REPLACE INTO items VALUES (?,?,?)",
                (key, value, time.time()),
            )
            self._conn.commit()

    def write_batch(self, items: list[tuple[int, str]]) -> None:
        """Flush many dirty items in a single DB round-trip."""
        with self._lock:
            self.access_count += 1          # одна операция, сколько бы строк ни было
            self._conn.executemany(
                "INSERT OR REPLACE INTO items VALUES (?,?,?)",
                [(k, v, time.time()) for k, v in items],
            )
            self._conn.commit()

    def reset_counter(self) -> None:
        self.access_count = 0
