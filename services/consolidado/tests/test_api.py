"""Testes da API HTTP (rodam no CI e no container; precisam de fastapi + httpx)."""

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.api import create_app  # noqa: E402
from app.consumer import tratar_mensagem  # noqa: E402
from app.service import ConsolidadoService  # noqa: E402

from .conftest import mensagem  # noqa: E402

CHAVE = {"X-API-Key": "chave-teste"}


@pytest.fixture
def client(db):
    return TestClient(create_app(db=db, api_keys=["chave-teste"], cache_ttl=0))


def test_sem_api_key_retorna_401(client):
    assert client.get("/api/v1/consolidado/diario/2026-11-13").status_code == 401


def test_saldo_do_dia(client, db):
    servico = ConsolidadoService(db, 0)
    tratar_mensagem(servico, json.dumps(mensagem("CREDITO", 15075)).encode())
    tratar_mensagem(servico, json.dumps(mensagem("DEBITO", 4200)).encode())

    r = client.get("/api/v1/consolidado/diario/2026-11-13", headers=CHAVE)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["total_creditos"] == "150.75"
    assert corpo["total_debitos"] == "42.00"
    assert corpo["saldo"] == "108.75"
    assert corpo["quantidade_lancamentos"] == 2


def test_periodo(client):
    r = client.get("/api/v1/consolidado/diario", headers=CHAVE,
                   params={"inicio": "2026-11-01", "fim": "2026-11-05"})
    assert r.status_code == 200
    assert len(r.json()) == 5
    r = client.get("/api/v1/consolidado/diario", headers=CHAVE,
                   params={"inicio": "2026-11-05", "fim": "2026-11-01"})
    assert r.status_code == 422


def test_data_invalida(client):
    assert client.get("/api/v1/consolidado/diario/ontem", headers=CHAVE).status_code == 422


def test_health_e_metricas(client):
    assert client.get("/health/ready").json() == {"status": "ok"}
    assert "http_requests_total" in client.get("/metrics").text
