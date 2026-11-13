"""API HTTP do serviço de Lançamentos (adaptador de entrada, FastAPI).

Documentação interativa (Swagger): http://localhost:8001/docs
"""

from __future__ import annotations

import hmac
import logging
import os
import time
import uuid
from datetime import date
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from .db import Database
from .domain import DomainError
from .observability import configurar_logs, correlation_id_var, metricas_http
from .repository import criar_schema
from .schemas import Erro, LancamentoResposta, NovoLancamento, PedidoEstorno
from .service import Conflito, LancamentoService, NaoEncontrado

log = logging.getLogger("lancamentos.api")


def create_app(db: Database | None = None, api_keys: list[str] | None = None) -> FastAPI:
    if db is None:
        configurar_logs("lancamentos", os.environ.get("LOG_LEVEL", "INFO"))
        db = Database(os.environ.get("DATABASE_URL", "sqlite:///lancamentos.db"))
    criar_schema(db)
    if api_keys is None:
        api_keys = [k.strip() for k in os.environ.get("API_KEYS", "dev-key-lancamentos").split(",") if k.strip()]

    servico = LancamentoService(db)
    metricas = metricas_http()

    app = FastAPI(
        title="Serviço de Lançamentos",
        version="1.0.0",
        description="Registra débitos e créditos do fluxo de caixa do comerciante. "
        "Cada lançamento gera o evento LancamentoRegistrado (Transactional Outbox).",
    )

    # ---------------- segurança ----------------
    def autenticar(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
        if not x_api_key or not any(hmac.compare_digest(x_api_key, k) for k in api_keys):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key ausente ou inválida")

    # ---------------- observabilidade ----------------
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

    @app.exception_handler(DomainError)
    async def erro_dominio(_: Request, exc: DomainError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    # ---------------- rotas de negócio ----------------
    erros = {401: {"model": Erro}, 422: {"model": Erro}}

    @app.post(
        "/api/v1/lancamentos",
        status_code=201,
        response_model=LancamentoResposta,
        responses={**erros, 200: {"model": LancamentoResposta, "description": "Repetição idempotente"},
                   409: {"model": Erro}},
        dependencies=[Depends(autenticar)],
        tags=["lançamentos"],
    )
    def registrar(
        corpo: NovoLancamento,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=100),
    ):
        try:
            lanc, criado = servico.registrar(
                corpo.tipo, corpo.valor, corpo.data_lancamento, corpo.descricao,
                chave_idempotencia=idempotency_key, correlation_id=correlation_id_var.get(),
            )
        except Conflito as exc:
            raise HTTPException(409, str(exc)) from exc
        if criado:
            metricas["lancamentos"].labels(lanc.tipo.value).inc()
            log.info("lancamento registrado", extra={"lancamento_id": lanc.id, "tipo": lanc.tipo.value})
        else:
            response.status_code = 200
        response.headers["Location"] = f"/api/v1/lancamentos/{lanc.id}"
        return LancamentoResposta.de(lanc)

    @app.post(
        "/api/v1/lancamentos/{lancamento_id}/estorno",
        status_code=201,
        response_model=LancamentoResposta,
        responses={**erros, 404: {"model": Erro}, 409: {"model": Erro}},
        dependencies=[Depends(autenticar)],
        tags=["lançamentos"],
    )
    def estornar(lancamento_id: UUID, corpo: PedidoEstorno | None = None):
        try:
            estorno = servico.estornar(str(lancamento_id), corpo.motivo if corpo else None,
                                       correlation_id=correlation_id_var.get())
        except NaoEncontrado as exc:
            raise HTTPException(404, str(exc)) from exc
        except Conflito as exc:
            raise HTTPException(409, str(exc)) from exc
        metricas["lancamentos"].labels(estorno.tipo.value).inc()
        log.info("estorno registrado", extra={"lancamento_id": estorno.id, "estorno_de": estorno.estorno_de})
        return LancamentoResposta.de(estorno)

    @app.get(
        "/api/v1/lancamentos/{lancamento_id}",
        response_model=LancamentoResposta,
        responses={**erros, 404: {"model": Erro}},
        dependencies=[Depends(autenticar)],
        tags=["lançamentos"],
    )
    def obter(lancamento_id: UUID):
        try:
            return LancamentoResposta.de(servico.obter(str(lancamento_id)))
        except NaoEncontrado as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get(
        "/api/v1/lancamentos",
        response_model=list[LancamentoResposta],
        responses=erros,
        dependencies=[Depends(autenticar)],
        tags=["lançamentos"],
    )
    def listar(
        data: date = Query(description="Dia dos lançamentos (AAAA-MM-DD)"),
        limite: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ):
        return [LancamentoResposta.de(item) for item in servico.listar_por_data(data, limite, offset)]

    # ---------------- operação ----------------
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


def app_factory() -> FastAPI:  # usado pelo uvicorn: --factory app.api:app_factory
    return create_app()
