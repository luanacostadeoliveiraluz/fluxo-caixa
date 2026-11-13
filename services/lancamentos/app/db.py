"""Adaptador de persistência (porta de saída) com SQL explícito.

Por que SQL explícito e não um ORM?
- O modelo é pequeno (2 tabelas por serviço) e o SQL fica legível na defesa.
- As duas operações críticas (outbox na mesma transação e UPSERT idempotente
  no consolidado) ficam visíveis, sem "mágica" de ORM.

O mesmo código roda em PostgreSQL (produção / docker compose) e em SQLite
(testes automatizados e execução local sem infraestrutura).
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Sequence


class Session:
    """Envelope fino sobre uma conexão DB-API dentro de uma transação."""

    def __init__(self, conn: Any, dialect: str) -> None:
        self._conn = conn
        self.dialect = dialect

    def _sql(self, sql: str) -> str:
        # Escrevemos o SQL com o placeholder do psycopg (%s);
        # o SQLite usa "?".
        return sql.replace("%s", "?") if self.dialect == "sqlite" else sql

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        cur = self._conn.cursor()
        cur.execute(self._sql(sql), tuple(params))
        return cur.rowcount

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        cur = self._conn.cursor()
        cur.execute(self._sql(sql), tuple(params))
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        cur = self._conn.cursor()
        cur.execute(self._sql(sql), tuple(params))
        return [dict(r) for r in cur.fetchall()]


class Database:
    """Fábrica de transações. URL: sqlite:///arquivo.db ou postgresql://..."""

    def __init__(self, url: str, pool_size: int = 10) -> None:
        self.url = url
        if url.startswith("sqlite:///"):
            self.dialect = "sqlite"
            self._path = url[len("sqlite:///"):]
            self._lock = threading.Lock()  # SQLite: um escritor por vez
            self._memory_conn: sqlite3.Connection | None = None
            if self._path == ":memory:":
                self._memory_conn = self._new_sqlite_conn()
        elif url.startswith(("postgresql://", "postgres://")):
            self.dialect = "postgres"
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(
                conninfo=url,
                min_size=1,
                max_size=pool_size,
                kwargs={"row_factory": dict_row},
                open=True,
            )
        else:
            raise ValueError(f"URL de banco não suportada: {url}")

    def _new_sqlite_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL") if self._path != ":memory:" else None
        return conn

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Abre uma transação: commit no sucesso, rollback em qualquer erro."""
        if self.dialect == "postgres":
            with self._pool.connection() as conn:  # commit/rollback automáticos
                yield Session(conn, self.dialect)
            return

        with self._lock:
            conn = self._memory_conn or self._new_sqlite_conn()
            try:
                yield Session(conn, self.dialect)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if self._memory_conn is None:
                    conn.close()

    def ping(self) -> bool:
        try:
            with self.transaction() as s:
                s.fetchone("SELECT 1 AS ok")
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self.dialect == "postgres":
            self._pool.close()
        elif self._memory_conn is not None:
            self._memory_conn.close()
