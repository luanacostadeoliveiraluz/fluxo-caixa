"""Casos de uso do Consolidado Diário: processar eventos e consultar saldos."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Generic, Hashable, TypeVar

from .db import Database
from .domain import LancamentoRegistrado, SaldoDiario
from .repository import SaldoRepository

V = TypeVar("V")
MAX_DIAS_PERIODO = 93


class TTLCache(Generic[V]):
    """Cache em memória com expiração (por instância da API).

    Por que existe: no pico de 50 req/s a maioria das consultas é do MESMO
    dia. Com TTL de poucos segundos, quase todas são respondidas da memória,
    sem ir ao banco. O custo é um atraso de no máximo TTL segundos, aceitável
    porque o consolidado já é eventualmente consistente.
    Em produção com muitas réplicas, pode ser trocado por Redis (ADR-0004).
    """

    def __init__(self, ttl_segundos: float, max_itens: int = 1024,
                 relogio: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl_segundos
        self.max_itens = max_itens
        self._relogio = relogio
        self._dados: dict[Hashable, tuple[float, V]] = {}
        self._lock = threading.Lock()
        self.acertos = 0
        self.falhas = 0

    def obter_ou_calcular(self, chave: Hashable, calcular: Callable[[], V]) -> V:
        agora = self._relogio()
        with self._lock:
            item = self._dados.get(chave)
            if item and item[0] > agora:
                self.acertos += 1
                return item[1]
            self.falhas += 1
        valor = calcular()
        with self._lock:
            if len(self._dados) >= self.max_itens:
                self._dados.clear()
            self._dados[chave] = (agora + self.ttl, valor)
        return valor


class ConsolidadoService:
    def __init__(self, db: Database, cache_ttl_segundos: float = 2.0) -> None:
        self.db = db
        self.repo = SaldoRepository()
        self.cache: TTLCache = TTLCache(cache_ttl_segundos)

    def processar(self, evento: LancamentoRegistrado) -> bool:
        """Aplica o evento. True = aplicado agora; False = duplicado (ignorado)."""
        with self.db.transaction() as s:
            return self.repo.aplicar(s, evento, datetime.now(timezone.utc))

    def saldo_do_dia(self, dia: date) -> SaldoDiario:
        def consultar() -> SaldoDiario:
            with self.db.transaction() as s:
                return self.repo.obter(s, dia) or SaldoDiario(data=dia)

        return self.cache.obter_ou_calcular(("dia", dia), consultar)

    def saldos_do_periodo(self, inicio: date, fim: date) -> list[SaldoDiario]:
        """Um item por dia do período, inclusive dias sem movimento (saldo zero)."""
        if fim < inicio:
            raise ValueError("fim deve ser maior ou igual a inicio")
        if (fim - inicio).days + 1 > MAX_DIAS_PERIODO:
            raise ValueError(f"período máximo de {MAX_DIAS_PERIODO} dias")

        def consultar() -> list[SaldoDiario]:
            with self.db.transaction() as s:
                existentes = {item.data: item for item in self.repo.periodo(s, inicio, fim)}
            dias = ((inicio + timedelta(days=i)) for i in range((fim - inicio).days + 1))
            return [existentes.get(d) or SaldoDiario(data=d) for d in dias]

        return self.cache.obter_ou_calcular(("periodo", inicio, fim), consultar)
