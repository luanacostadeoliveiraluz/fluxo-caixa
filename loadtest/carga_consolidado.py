"""Teste de carga do requisito não funcional do Consolidado.

Requisito: em dias de pico, 50 requisições/segundo com no máximo 5% de perda.

Uso (com o docker compose no ar):
    python loadtest/carga_consolidado.py --rps 50 --segundos 60

Só usa a biblioteca padrão do Python: não precisa instalar nada.
Dispara as requisições num ritmo fixo (modelo "open": não espera a anterior
terminar), como acontece com clientes reais, e mede perda e latência.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta


def requisitar(url: str, api_key: str, timeout: float) -> tuple[bool, float]:
    inicio = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"X-API-Key": api_key})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            ok = resp.status == 200
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        ok = False
    return ok, time.perf_counter() - inicio


def executar(base_url: str, api_key: str, rps: int, segundos: int, timeout: float) -> dict:
    hoje = date.today()
    # 80% das consultas são do dia atual (o padrão real de uso), 20% de dias recentes
    urls = [f"{base_url}/api/v1/consolidado/diario/{hoje.isoformat()}"] * 8 + [
        f"{base_url}/api/v1/consolidado/diario/{(hoje - timedelta(days=d)).isoformat()}" for d in (1, 2)
    ]
    resultados: list[tuple[bool, float]] = []
    trava = threading.Lock()
    total = rps * segundos
    intervalo = 1.0 / rps

    def tarefa(i: int) -> None:
        r = requisitar(urls[i % len(urls)], api_key, timeout)
        with trava:
            resultados.append(r)

    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(rps * 2, 10)) as pool:
        for i in range(total):
            alvo = inicio + i * intervalo
            espera = alvo - time.perf_counter()
            if espera > 0:
                time.sleep(espera)
            pool.submit(tarefa, i)
    duracao = time.perf_counter() - inicio

    latencias = sorted(lat for ok, lat in resultados if ok)
    falhas = sum(1 for ok, _ in resultados if not ok)

    def pct(p: float) -> float:
        return latencias[min(len(latencias) - 1, int(len(latencias) * p))] * 1000 if latencias else float("nan")

    return {
        "enviadas": total,
        "sucesso": total - falhas,
        "falhas": falhas,
        "perda_pct": 100.0 * falhas / total if total else 0.0,
        "rps_efetivo": total / duracao,
        "lat_media_ms": statistics.mean(latencias) * 1000 if latencias else float("nan"),
        "lat_p95_ms": pct(0.95),
        "lat_p99_ms": pct(0.99),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8002")
    ap.add_argument("--api-key", default="dev-key-consolidado")
    ap.add_argument("--rps", type=int, default=50)
    ap.add_argument("--segundos", type=int, default=60)
    ap.add_argument("--timeout", type=float, default=2.0, help="acima disso conta como perda")
    ap.add_argument("--perda-maxima", type=float, default=5.0)
    args = ap.parse_args()

    print(f"Disparando {args.rps} req/s por {args.segundos}s em {args.url} ...")
    r = executar(args.url, args.api_key, args.rps, args.segundos, args.timeout)
    print(
        f"\nEnviadas: {r['enviadas']}  Sucesso: {r['sucesso']}  Falhas: {r['falhas']}\n"
        f"Perda: {r['perda_pct']:.2f}%  (limite {args.perda_maxima}%)\n"
        f"Taxa efetiva: {r['rps_efetivo']:.1f} req/s\n"
        f"Latência média: {r['lat_media_ms']:.1f} ms | p95: {r['lat_p95_ms']:.1f} ms | p99: {r['lat_p99_ms']:.1f} ms"
    )
    aprovado = r["perda_pct"] <= args.perda_maxima
    print("\nRESULTADO:", "APROVADO" if aprovado else "REPROVADO")
    return 0 if aprovado else 1


if __name__ == "__main__":
    sys.exit(main())
