"""Observabilidade: logs estruturados em JSON + correlation id + métricas.

- Logs em JSON: prontos para Loki / CloudWatch / Elastic, pesquisáveis por campo.
- correlation_id: viaja do header HTTP X-Correlation-ID para o evento no
  RabbitMQ e para os logs do consolidado. Permite seguir uma operação
  de ponta a ponta entre os serviços.
- Métricas Prometheus: expostas em /metrics (API) e numa porta própria (relay).
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_CAMPOS_PADRAO = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def __init__(self, servico: str) -> None:
        super().__init__()
        self.servico = servico

    def format(self, record: logging.LogRecord) -> str:
        dados = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "nivel": record.levelname,
            "servico": self.servico,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
        }
        for chave, valor in record.__dict__.items():
            if chave not in _CAMPOS_PADRAO and not chave.startswith("_"):
                dados[chave] = valor
        if record.exc_info:
            dados["erro"] = self.formatException(record.exc_info)
        return json.dumps(dados, ensure_ascii=False, default=str)


def configurar_logs(servico: str = "consolidado", nivel: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(servico))
    raiz = logging.getLogger()
    raiz.handlers[:] = [handler]
    raiz.setLevel(nivel)


# --- Métricas (prometheus_client é importado só quando necessário) ---------

_metricas: dict = {}


def metricas_http():
    if not _metricas:
        from prometheus_client import Counter, Histogram

        _metricas["requisicoes"] = Counter(
            "http_requests_total", "Requisições HTTP", ["metodo", "rota", "status"]
        )
        _metricas["latencia"] = Histogram(
            "http_request_duration_seconds", "Latência HTTP", ["metodo", "rota"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
        )
    return _metricas
