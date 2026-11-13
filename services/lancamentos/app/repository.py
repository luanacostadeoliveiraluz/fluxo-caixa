"""Repositórios do serviço de Lançamentos + Transactional Outbox.

Transactional Outbox: o lançamento e o evento "LancamentoRegistrado" são
gravados NA MESMA transação. Assim nunca existe lançamento sem evento
(nem evento sem lançamento), mesmo que o RabbitMQ esteja fora do ar.
Um processo separado (outbox_relay) publica os eventos pendentes depois.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from .db import Database, Session
from .domain import Lancamento, TipoLancamento, evento_lancamento_registrado

SCHEMA = {
    "postgres": [
        """
        CREATE TABLE IF NOT EXISTS lancamentos (
            id                  UUID PRIMARY KEY,
            tipo                VARCHAR(7)   NOT NULL CHECK (tipo IN ('CREDITO','DEBITO')),
            valor_centavos      BIGINT       NOT NULL CHECK (valor_centavos > 0),
            data_lancamento     DATE         NOT NULL,
            descricao           VARCHAR(200),
            criado_em           TIMESTAMPTZ  NOT NULL,
            estorno_de          UUID UNIQUE REFERENCES lancamentos(id),
            chave_idempotencia  VARCHAR(100) UNIQUE
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_lancamentos_data ON lancamentos (data_lancamento)",
        """
        CREATE TABLE IF NOT EXISTS outbox (
            id             BIGSERIAL PRIMARY KEY,
            event_id       UUID         NOT NULL UNIQUE,
            event_type     VARCHAR(100) NOT NULL,
            payload        TEXT         NOT NULL,
            correlation_id VARCHAR(100),
            criado_em      TIMESTAMPTZ  NOT NULL,
            publicado_em   TIMESTAMPTZ,
            tentativas     INT          NOT NULL DEFAULT 0
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_outbox_pendentes ON outbox (id) WHERE publicado_em IS NULL",
    ],
    "sqlite": [
        """
        CREATE TABLE IF NOT EXISTS lancamentos (
            id                  TEXT PRIMARY KEY,
            tipo                TEXT    NOT NULL CHECK (tipo IN ('CREDITO','DEBITO')),
            valor_centavos      INTEGER NOT NULL CHECK (valor_centavos > 0),
            data_lancamento     TEXT    NOT NULL,
            descricao           TEXT,
            criado_em           TEXT    NOT NULL,
            estorno_de          TEXT UNIQUE REFERENCES lancamentos(id),
            chave_idempotencia  TEXT UNIQUE
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_lancamentos_data ON lancamentos (data_lancamento)",
        """
        CREATE TABLE IF NOT EXISTS outbox (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id       TEXT    NOT NULL UNIQUE,
            event_type     TEXT    NOT NULL,
            payload        TEXT    NOT NULL,
            correlation_id TEXT,
            criado_em      TEXT    NOT NULL,
            publicado_em   TEXT,
            tentativas     INTEGER NOT NULL DEFAULT 0
        )
        """,
    ],
}


def criar_schema(db: Database) -> None:
    """Cria as tabelas se não existirem (várias réplicas podem subir juntas)."""
    with db.transaction() as s:
        if db.dialect == "postgres":
            # trava para que réplicas simultâneas não criem o schema ao mesmo tempo
            s.execute("SELECT pg_advisory_xact_lock(1001)")
        for ddl in SCHEMA[db.dialect]:
            s.execute(ddl)


def _as_date(v) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v))


def _as_datetime(v) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def _to_lancamento(row: dict) -> Lancamento:
    return Lancamento(
        id=str(row["id"]),
        tipo=TipoLancamento(row["tipo"]),
        valor_centavos=int(row["valor_centavos"]),
        data_lancamento=_as_date(row["data_lancamento"]),
        descricao=row["descricao"],
        criado_em=_as_datetime(row["criado_em"]),
        estorno_de=str(row["estorno_de"]) if row["estorno_de"] else None,
        chave_idempotencia=row["chave_idempotencia"],
    )


_COLUNAS = "id, tipo, valor_centavos, data_lancamento, descricao, criado_em, estorno_de, chave_idempotencia"


class LancamentoRepository:
    def adicionar_com_evento(
        self, s: Session, lanc: Lancamento, correlation_id: str | None = None
    ) -> dict:
        """Grava o lançamento e o evento no outbox (mesma transação)."""
        s.execute(
            f"INSERT INTO lancamentos ({_COLUNAS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                lanc.id,
                lanc.tipo.value,
                lanc.valor_centavos,
                lanc.data_lancamento.isoformat(),
                lanc.descricao,
                lanc.criado_em.isoformat(),
                lanc.estorno_de,
                lanc.chave_idempotencia,
            ),
        )
        evento = evento_lancamento_registrado(lanc)
        s.execute(
            "INSERT INTO outbox (event_id, event_type, payload, correlation_id, criado_em) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                evento["event_id"],
                evento["event_type"],
                json.dumps(evento),
                correlation_id,
                lanc.criado_em.isoformat(),
            ),
        )
        return evento

    def obter(self, s: Session, lancamento_id: str) -> Lancamento | None:
        row = s.fetchone(f"SELECT {_COLUNAS} FROM lancamentos WHERE id = %s", (lancamento_id,))
        return _to_lancamento(row) if row else None

    def obter_por_chave(self, s: Session, chave: str) -> Lancamento | None:
        row = s.fetchone(
            f"SELECT {_COLUNAS} FROM lancamentos WHERE chave_idempotencia = %s", (chave,)
        )
        return _to_lancamento(row) if row else None

    def obter_estorno_de(self, s: Session, lancamento_id: str) -> Lancamento | None:
        row = s.fetchone(f"SELECT {_COLUNAS} FROM lancamentos WHERE estorno_de = %s", (lancamento_id,))
        return _to_lancamento(row) if row else None

    def listar_por_data(self, s: Session, dia: date, limite: int = 500, offset: int = 0) -> list[Lancamento]:
        rows = s.fetchall(
            f"SELECT {_COLUNAS} FROM lancamentos WHERE data_lancamento = %s "
            "ORDER BY criado_em, id LIMIT %s OFFSET %s",
            (dia.isoformat(), limite, offset),
        )
        return [_to_lancamento(r) for r in rows]


class OutboxRepository:
    def pendentes(self, s: Session, limite: int) -> list[dict]:
        # SKIP LOCKED permite rodar mais de um relay em paralelo (escala
        # horizontal) sem que dois relays peguem o mesmo evento.
        lock = " FOR UPDATE SKIP LOCKED" if s.dialect == "postgres" else ""
        return s.fetchall(
            "SELECT id, event_id, event_type, payload, correlation_id FROM outbox "
            f"WHERE publicado_em IS NULL ORDER BY id LIMIT %s{lock}",
            (limite,),
        )

    def marcar_publicado(self, s: Session, outbox_id: int, quando: datetime) -> None:
        s.execute(
            "UPDATE outbox SET publicado_em = %s, tentativas = tentativas + 1 WHERE id = %s",
            (quando.isoformat(), outbox_id),
        )

    def registrar_falha(self, s: Session, outbox_id: int) -> None:
        s.execute("UPDATE outbox SET tentativas = tentativas + 1 WHERE id = %s", (outbox_id,))

    def contar_pendentes(self, s: Session) -> int:
        row = s.fetchone("SELECT COUNT(*) AS n FROM outbox WHERE publicado_em IS NULL")
        return int(row["n"]) if row else 0
