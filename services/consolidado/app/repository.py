"""Persistência do read model do consolidado + controle de idempotência."""

from __future__ import annotations

from datetime import date, datetime

from .db import Database, Session
from .domain import LancamentoRegistrado, SaldoDiario

SCHEMA = {
    "postgres": [
        """
        CREATE TABLE IF NOT EXISTS saldo_diario (
            data                     DATE PRIMARY KEY,
            total_creditos_centavos  BIGINT      NOT NULL DEFAULT 0,
            total_debitos_centavos   BIGINT      NOT NULL DEFAULT 0,
            quantidade_lancamentos   INT         NOT NULL DEFAULT 0,
            atualizado_em            TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS eventos_processados (
            event_id       UUID PRIMARY KEY,
            lancamento_id  UUID        NOT NULL,
            processado_em  TIMESTAMPTZ NOT NULL
        )
        """,
    ],
    "sqlite": [
        """
        CREATE TABLE IF NOT EXISTS saldo_diario (
            data                     TEXT PRIMARY KEY,
            total_creditos_centavos  INTEGER NOT NULL DEFAULT 0,
            total_debitos_centavos   INTEGER NOT NULL DEFAULT 0,
            quantidade_lancamentos   INTEGER NOT NULL DEFAULT 0,
            atualizado_em            TEXT    NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS eventos_processados (
            event_id       TEXT PRIMARY KEY,
            lancamento_id  TEXT NOT NULL,
            processado_em  TEXT NOT NULL
        )
        """,
    ],
}


def criar_schema(db: Database) -> None:
    """Cria as tabelas se não existirem (várias réplicas podem subir juntas)."""
    with db.transaction() as s:
        if db.dialect == "postgres":
            # trava para que réplicas simultâneas não criem o schema ao mesmo tempo
            s.execute("SELECT pg_advisory_xact_lock(1002)")
        for ddl in SCHEMA[db.dialect]:
            s.execute(ddl)


def _as_date(v) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v))


def _to_saldo(row: dict) -> SaldoDiario:
    atualizado = row["atualizado_em"]
    return SaldoDiario(
        data=_as_date(row["data"]),
        total_creditos_centavos=int(row["total_creditos_centavos"]),
        total_debitos_centavos=int(row["total_debitos_centavos"]),
        quantidade_lancamentos=int(row["quantidade_lancamentos"]),
        atualizado_em=atualizado if isinstance(atualizado, datetime) else datetime.fromisoformat(atualizado),
    )


class SaldoRepository:
    def aplicar(self, s: Session, evento: LancamentoRegistrado, agora: datetime) -> bool:
        """Aplica o evento ao saldo do dia. Retorna False se já tinha sido aplicado.

        Os dois comandos rodam na MESMA transação:
        1) registra o event_id (PK impede duplicidade);
        2) soma o valor no dia com UPSERT atômico (seguro com vários consumidores).
        """
        inseridos = s.execute(
            "INSERT INTO eventos_processados (event_id, lancamento_id, processado_em) "
            "VALUES (%s, %s, %s) ON CONFLICT (event_id) DO NOTHING",
            (evento.event_id, evento.lancamento_id, agora.isoformat()),
        )
        if inseridos == 0:
            return False  # duplicado: entrega "pelo menos uma vez" do broker
        s.execute(
            """
            INSERT INTO saldo_diario
                (data, total_creditos_centavos, total_debitos_centavos, quantidade_lancamentos, atualizado_em)
            VALUES (%s, %s, %s, 1, %s)
            ON CONFLICT (data) DO UPDATE SET
                total_creditos_centavos = saldo_diario.total_creditos_centavos + excluded.total_creditos_centavos,
                total_debitos_centavos  = saldo_diario.total_debitos_centavos  + excluded.total_debitos_centavos,
                quantidade_lancamentos  = saldo_diario.quantidade_lancamentos + 1,
                atualizado_em           = excluded.atualizado_em
            """,
            (
                evento.data_lancamento.isoformat(),
                evento.credito_centavos,
                evento.debito_centavos,
                agora.isoformat(),
            ),
        )
        return True

    def obter(self, s: Session, dia: date) -> SaldoDiario | None:
        row = s.fetchone("SELECT * FROM saldo_diario WHERE data = %s", (dia.isoformat(),))
        return _to_saldo(row) if row else None

    def periodo(self, s: Session, inicio: date, fim: date) -> list[SaldoDiario]:
        rows = s.fetchall(
            "SELECT * FROM saldo_diario WHERE data BETWEEN %s AND %s ORDER BY data",
            (inicio.isoformat(), fim.isoformat()),
        )
        return [_to_saldo(r) for r in rows]
