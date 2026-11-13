"""Consumidor RabbitMQ: transforma eventos LancamentoRegistrado em saldo diário.

Decisões de resiliência:
- ack manual: a mensagem só sai da fila DEPOIS que o saldo foi gravado;
- evento inválido (nunca vai funcionar)  -> DLQ (fila de mensagens mortas);
- erro temporário (ex.: banco fora)      -> volta para a fila e tenta de novo;
- prefetch limitado: controla quantas mensagens ficam "em mãos" (backpressure);
- se o consumidor cair, as mensagens ficam guardadas na fila durável.
"""

from __future__ import annotations

import json
import logging
import os
import time
from enum import Enum

from .domain import EventoInvalido, LancamentoRegistrado
from .observability import correlation_id_var
from .service import ConsolidadoService

log = logging.getLogger("consolidado.consumer")

EXCHANGE = "fluxo-caixa.eventos"
EXCHANGE_DLX = "fluxo-caixa.dlx"
FILA = "consolidado.lancamentos"
FILA_DLQ = "consolidado.lancamentos.dlq"
ROUTING_KEY = "lancamento.registrado"


class Resultado(str, Enum):
    PROCESSADO = "processado"
    DUPLICADO = "duplicado"
    INVALIDO = "invalido"        # -> DLQ
    TENTAR_DE_NOVO = "retry"     # -> requeue


def tratar_mensagem(servico: ConsolidadoService, corpo: bytes, correlation_id: str | None = None) -> Resultado:
    token = correlation_id_var.set(correlation_id)
    try:
        try:
            evento = LancamentoRegistrado.de_mensagem(json.loads(corpo))
        except (EventoInvalido, json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.error("evento inválido enviado para DLQ", extra={"motivo": str(exc)})
            return Resultado.INVALIDO
        try:
            aplicado = servico.processar(evento)
        except Exception:
            log.exception("falha temporária ao processar evento", extra={"event_id": evento.event_id})
            return Resultado.TENTAR_DE_NOVO
        log.info("evento processado" if aplicado else "evento duplicado ignorado",
                 extra={"event_id": evento.event_id, "data": evento.data_lancamento.isoformat()})
        return Resultado.PROCESSADO if aplicado else Resultado.DUPLICADO
    finally:
        correlation_id_var.reset(token)


def declarar_topologia(canal) -> None:
    canal.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
    canal.exchange_declare(EXCHANGE_DLX, exchange_type="fanout", durable=True)
    canal.queue_declare(FILA_DLQ, durable=True)
    canal.queue_bind(FILA_DLQ, EXCHANGE_DLX)
    canal.queue_declare(FILA, durable=True, arguments={"x-dead-letter-exchange": EXCHANGE_DLX})
    canal.queue_bind(FILA, EXCHANGE, routing_key=ROUTING_KEY)


def main() -> None:  # pragma: no cover - processo de longa duração
    import pika
    from pika.exceptions import AMQPError
    from prometheus_client import Counter, start_http_server

    from .db import Database
    from .observability import configurar_logs
    from .repository import criar_schema

    configurar_logs("consolidado-consumer")
    start_http_server(int(os.environ.get("METRICS_PORT", "9100")))
    contador = Counter("consolidado_eventos_total", "Eventos consumidos por resultado", ["resultado"])

    db = Database(os.environ.get("DATABASE_URL", "sqlite:///consolidado.db"))
    criar_schema(db)
    servico = ConsolidadoService(db)
    prefetch = int(os.environ.get("PREFETCH", "50"))

    def ao_receber(canal, metodo, props, corpo):
        resultado = tratar_mensagem(servico, corpo, props.correlation_id)
        contador.labels(resultado.value).inc()
        if resultado is Resultado.INVALIDO:
            canal.basic_nack(metodo.delivery_tag, requeue=False)  # -> DLQ
        elif resultado is Resultado.TENTAR_DE_NOVO:
            time.sleep(1)  # pequeno recuo antes de devolver
            canal.basic_nack(metodo.delivery_tag, requeue=True)
        else:
            canal.basic_ack(metodo.delivery_tag)

    while True:
        try:
            conexao = pika.BlockingConnection(pika.URLParameters(os.environ["RABBITMQ_URL"]))
            canal = conexao.channel()
            declarar_topologia(canal)
            canal.basic_qos(prefetch_count=prefetch)
            canal.basic_consume(FILA, ao_receber)
            log.info("consumidor iniciado", extra={"fila": FILA})
            canal.start_consuming()
        except AMQPError:
            log.warning("RabbitMQ indisponível; nova tentativa em 5s")
            time.sleep(5)


if __name__ == "__main__":  # pragma: no cover
    main()
