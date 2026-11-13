"""API HTTP do Consolidado Diário (somente leitura).

Documentação interativa (Swagger): http://localhost:8002/docs
"""

from __future__ import annotations

import hmac
import os
import time
import uuid
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status

from .db import Database
from .observability import configurar_logs, correlation_id_var, metricas_http
from .repository import criar_schema
from .schemas import Erro, SaldoDiarioResposta
from .service import ConsolidadoService


def create_app(db: Database | None = None, api_keys: list[str] | None = None,
               cache_ttl: float | None = None) -> FastAPI:
    if db is None:
        configurar_logs("consolidado-api", os.environ.get("LOG_LEVEL", "INFO"))
        db = Database(os.environ.get("DATABASE_URL", "sqlite:///consolidado.db"),
                      pool_size=int(os.environ.get("DB_POOL_SIZE", "20")))
    criar_schema(db)
    if api_keys is None:
        api_keys = [k.strip() for k in os.environ.get("API_KEYS", "dev-key-consolidado").split(",") if k.strip()]
    if cache_ttl is None:
        cache_ttl = float(os.environ.get("CACHE_TTL_SEGUNDOS", "2"))

    servico = ConsolidadoService(db, cache_ttl)
    metricas = metricas_http()

    app = FastAPI(
        title="Serviço de Consolidado Diário",
        version="1.0.0",
        description="Saldo diário consolidado (créditos - débitos) do comerciante. "
        "Modelo de leitura alimentado por eventos; eventualmente consistente (segundos).",
    )

    def autenticar(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
        if not x_api_key or not any(hmac.compare_digest(x_api_key, k) for k in api_keys):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key ausente ou inválida")

    @app.middleware("http")
    async def correlacao_e_metricas(request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        token = correlation_id_var.set(cid)
        inicio = time.perf_counter()
        try:
            resposta = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        rota = request.scope.get("route").path if request.scope.get("route") else "nao_mapeada"
        metricas["requisicoes"].labels(request.method, rota, resposta.status_code).inc()
        metricas["latencia"].labels(request.method, rota).observe(time.perf_counter() - inicio)
        resposta.headers["X-Correlation-ID"] = cid
        return resposta

    erros = {401: {"model": Erro}, 422: {"model": Erro}}

    @app.get(
        "/api/v1/consolidado/diario/{data}",
        response_model=SaldoDiarioResposta,
        responses=erros,
        dependencies=[Depends(autenticar)],
        tags=["consolidado"],
    )
    def saldo_do_dia(data: date, response: Response):
        response.headers["Cache-Control"] = f"private, max-age={int(cache_ttl)}"
        return SaldoDiarioResposta.de(servico.saldo_do_dia(data))

    @app.get(
        "/api/v1/consolidado/diario",
        response_model=list[SaldoDiarioResposta],
        responses=erros,
        dependencies=[Depends(autenticar)],
        tags=["consolidado"],
    )
    def saldos_do_periodo(
        inicio: date = Query(description="Primeiro dia (AAAA-MM-DD)"),
        fim: date = Query(description="Último dia (AAAA-MM-DD), máximo 93 dias"),
    ):
        try:
            return [SaldoDiarioResposta.de(item) for item in servico.saldos_do_periodo(inicio, fim)]
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/health/live", tags=["operação"])
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["operação"])
    def ready():
        if not db.ping():
            raise HTTPException(503, "banco indisponível")
        return {"status": "ok"}

    @app.get("/metrics", tags=["operação"], include_in_schema=False)
    def metrics():
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


def app_factory() -> FastAPI:
    return create_app()
