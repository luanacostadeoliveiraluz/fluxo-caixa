"""Testes da API HTTP (rodam no CI e no container; precisam de fastapi + httpx)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.api import create_app  # noqa: E402

CHAVE = {"X-API-Key": "chave-teste"}


@pytest.fixture
def client(db):
    return TestClient(create_app(db=db, api_keys=["chave-teste"]))


def test_sem_api_key_retorna_401(client):
    assert client.post("/api/v1/lancamentos", json={"tipo": "CREDITO", "valor": "1"}).status_code == 401


def test_registrar_e_consultar(client):
    r = client.post("/api/v1/lancamentos", headers={**CHAVE, "X-Correlation-ID": "cid-42"},
                    json={"tipo": "CREDITO", "valor": "150.75", "descricao": "Venda"})
    assert r.status_code == 201, r.text
    assert r.headers["X-Correlation-ID"] == "cid-42"
    corpo = r.json()
    assert corpo["valor"] == "150.75"
    assert r.headers["Location"] == f"/api/v1/lancamentos/{corpo['id']}"

    r2 = client.get(f"/api/v1/lancamentos/{corpo['id']}", headers=CHAVE)
    assert r2.status_code == 200
    assert r2.json()["id"] == corpo["id"]


def test_validacoes_retorna_422(client):
    for corpo in ({"tipo": "PIX", "valor": "1"}, {"tipo": "CREDITO", "valor": "-1"},
                  {"tipo": "CREDITO", "valor": "1.234"}, {"tipo": "CREDITO", "valor": "1",
                                                          "data_lancamento": "2999-01-01"}):
        assert client.post("/api/v1/lancamentos", headers=CHAVE, json=corpo).status_code == 422


def test_idempotencia(client):
    h = {**CHAVE, "Idempotency-Key": "abc-1"}
    r1 = client.post("/api/v1/lancamentos", headers=h, json={"tipo": "DEBITO", "valor": "5"})
    r2 = client.post("/api/v1/lancamentos", headers=h, json={"tipo": "DEBITO", "valor": "5"})
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r1.json()["id"] == r2.json()["id"]


def test_estorno_e_listagem(client):
    r = client.post("/api/v1/lancamentos", headers=CHAVE, json={"tipo": "CREDITO", "valor": "20"})
    lanc = r.json()
    e = client.post(f"/api/v1/lancamentos/{lanc['id']}/estorno", headers=CHAVE, json={"motivo": "erro"})
    assert e.status_code == 201
    assert e.json()["tipo"] == "DEBITO"
    assert client.post(f"/api/v1/lancamentos/{lanc['id']}/estorno", headers=CHAVE).status_code == 409

    lista = client.get("/api/v1/lancamentos", headers=CHAVE, params={"data": lanc["data_lancamento"]})
    assert lista.status_code == 200
    assert len(lista.json()) == 2


def test_nao_encontrado(client):
    r = client.get("/api/v1/lancamentos/00000000-0000-0000-0000-000000000000", headers=CHAVE)
    assert r.status_code == 404


def test_health_e_metricas(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").status_code == 200
    assert "http_requests_total" in client.get("/metrics").text
