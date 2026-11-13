"""Outbox Relay: publica no RabbitMQ os eventos gravados na tabela outbox.

Roda como processo separado da API. Se o RabbitMQ (ou o serviço de
consolidado) estiver fora do ar, a API de lançamentos continua aceitando
lançamentos normalmente; os eventos ficam pendentes no outbox e são
publicados quando o broker voltar.

Garantia de entrega: "pelo menos uma vez" (at-least-once). Se a publicação
der certo e o UPDATE falhar, o evento é publicado de novo; por isso o
consumidor do consolidado é idempotente (deduplica por event_id).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Protocol

from .db import Database
from .domain import agora_utc
from .repository import OutboxRepository, criar_schema

log = logging.getLogger("lancamentos.outbox_relay")

EXCHANGE = "fluxo-caixa.eventos"
ROUTING_KEYS = {"LancamentoRegistrado": "lancamento.registrado"}


class Publisher(Protocol):
    def publicar(self, routing_key: str, evento: dict, correlation_id: str | None) -> None:
        """Deve lançar exceção se o broker não confirmar a mensagem."""


class OutboxRelay:
    def __init__(self, db: Database, publisher: Publisher, lote: int = 100) -> None:
        self.db = db
        self.publisher = publisher
        self.lote = lote
        self.repo = OutboxRepository()

    def executar_uma_vez(self) -> int:
        """Publica um lote de eventos pendentes. Retorna quantos publicou."""
        publicados = 0
        with self.db.transaction() as s:
            for item in self.repo.pendentes(s, self.lote):
                evento = json.loads(item["payload"])
                routing_key = ROUTING_KEYS.get(item["event_type"], "desconhecido")
                try:
                    self.publisher.publicar(routing_key, evento, item["correlation_id"])
                except Exception:
                    log.exception("falha ao publicar evento", extra={"event_id": str(item["event_id"])})
                    self.repo.registrar_falha(s, item["id"])
                    break  # preserva a ordem: tenta de novo no próximo ciclo
                self.repo.marcar_publicado(s, item["id"], agora_utc())
                publicados += 1
        return publicados

    def pendentes(self) -> int:
        with self.db.transaction() as s:
            return self.repo.contar_pendentes(s)


class RabbitPublisher:
    """Adaptador RabbitMQ (pika) com publisher confirms e mensagens persistentes."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._conn = None
        self._channel = None

    def _canal(self):
        import pika

        if self._channel is None or self._channel.is_closed:
            self._conn = pika.BlockingConnection(pika.URLParameters(self.url))
            self._channel = self._conn.channel()
            self._channel.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
            self._channel.confirm_delivery()  # broker confirma o recebimento
        return self._channel

    def publicar(self, routing_key: str, evento: dict, correlation_id: str | None) -> None:
        import pika

        try:
            self._canal().basic_publish(
                exchange=EXCHANGE,
                routing_key=routing_key,
                body=json.dumps(evento).encode("utf-8"),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,  # persistente em disco
                    message_id=evento["event_id"],
                    type=evento["event_type"],
                    correlation_id=correlation_id,
                ),
                # mandatory: se ainda não existe fila ligada, o broker devolve
                # a mensagem e ela continua pendente no outbox (não se perde).
                mandatory=True,
            )
        except Exception:
            self._fechar()
            raise

    def _fechar(self) -> None:
        try:
            if self._conn is not None and self._conn.is_open:
                self._conn.close()
        except Exception:
            pass
        self._conn = None
        self._channel = None


def main() -> None:  # pragma: no cover - processo de longa duração
    from .observability import configurar_logs, iniciar_metricas_relay

    configurar_logs()
    db = Database(os.environ.get("DATABASE_URL", "sqlite:///lancamentos.db"))
    criar_schema(db)
    relay = OutboxRelay(db, RabbitPublisher(os.environ["RABBITMQ_URL"]),
                        lote=int(os.environ.get("OUTBOX_LOTE", "100")))
    intervalo = float(os.environ.get("OUTBOX_INTERVALO_SEGUNDOS", "0.5"))
    gauge = iniciar_metricas_relay(int(os.environ.get("METRICS_PORT", "9100")))
    log.info("outbox relay iniciado")
    while True:
        try:
            n = relay.executar_uma_vez()
            gauge.set(relay.pendentes())
        except Exception:
            log.exception("erro no ciclo do relay")
            n = 0
        if n == 0:
            time.sleep(intervalo)


if __name__ == "__main__":  # pragma: no cover
    main()
