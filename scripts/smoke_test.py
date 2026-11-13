"""Teste de ponta a ponta com o ambiente do docker compose no ar.

Verifica o fluxo completo e o requisito de resiliência:
1. registra créditos e débitos na API de Lançamentos;
2. espera o consolidado refletir o saldo (consistência eventual);
3. estorna um lançamento e confere o novo saldo.

Uso:  python scripts/smoke_test.py
Só usa a biblioteca padrão do Python.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date
from decimal import Decimal

LANC = "http://localhost:8001"
CONS = "http://localhost:8002"
KEY_L = {"X-API-Key": "dev-key-lancamentos"}
KEY_C = {"X-API-Key": "dev-key-consolidado"}


def chamar(metodo: str, url: str, headers: dict, corpo: dict | None = None) -> tuple[int, dict]:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo,
                                 headers={**headers, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def esperar_pronto(url: str, segundos: int = 90) -> None:
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            with urllib.request.urlopen(f"{url}/health/ready", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit(f"{url} não ficou pronto em {segundos}s")


def saldo_hoje() -> Decimal:
    status, corpo = chamar("GET", f"{CONS}/api/v1/consolidado/diario/{date.today().isoformat()}", KEY_C)
    assert status == 200, corpo
    return Decimal(corpo["saldo"])


def esperar_saldo(esperado: Decimal, segundos: int = 30) -> None:
    limite = time.time() + segundos
    atual = None
    while time.time() < limite:
        atual = saldo_hoje()
        if atual == esperado:
            return
        time.sleep(1)
    raise AssertionError(f"saldo esperado {esperado}, obtido {atual}")


def main() -> int:
    esperar_pronto(LANC)
    esperar_pronto(CONS)
    inicial = saldo_hoje()
    print(f"saldo inicial de hoje: {inicial}")

    marca = uuid.uuid4().hex[:6]
    st, credito = chamar("POST", f"{LANC}/api/v1/lancamentos", KEY_L,
                         {"tipo": "CREDITO", "valor": "150.75", "descricao": f"smoke {marca}"})
    assert st == 201, credito
    st, _ = chamar("POST", f"{LANC}/api/v1/lancamentos", KEY_L,
                   {"tipo": "DEBITO", "valor": "50.25", "descricao": f"smoke {marca}"})
    assert st == 201

    esperar_saldo(inicial + Decimal("100.50"))
    print("ok: consolidado refletiu crédito e débito")

    st, _ = chamar("POST", f"{LANC}/api/v1/lancamentos/{credito['id']}/estorno", KEY_L, {"motivo": "smoke"})
    assert st == 201
    esperar_saldo(inicial + Decimal("-50.25"))
    print("ok: estorno refletido no consolidado")

    st, _ = chamar("GET", f"{LANC}/api/v1/lancamentos/{credito['id']}", {})
    assert st == 401
    print("ok: chamada sem API key foi recusada")
    print("\nSMOKE TEST APROVADO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
