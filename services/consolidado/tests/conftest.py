import uuid
from datetime import date

import pytest

from app.db import Database
from app.repository import criar_schema


@pytest.fixture
def db(tmp_path):
    banco = Database(f"sqlite:///{tmp_path / 'teste.db'}")
    criar_schema(banco)
    yield banco
    banco.close()


def mensagem(tipo="CREDITO", valor=1000, dia=date(2026, 11, 13), event_id=None):
    """Monta um evento LancamentoRegistrado v1 como o publicado pelo serviço de lançamentos."""
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": "LancamentoRegistrado",
        "event_version": 1,
        "occurred_at": "2026-11-13T12:00:00+00:00",
        "data": {
            "lancamento_id": str(uuid.uuid4()),
            "tipo": tipo,
            "valor_centavos": valor,
            "data_lancamento": dia.isoformat(),
            "estorno_de": None,
        },
    }
