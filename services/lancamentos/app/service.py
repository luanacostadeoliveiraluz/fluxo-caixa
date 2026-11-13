"""Casos de uso (camada de aplicação) do serviço de Lançamentos.

Não conhece HTTP nem RabbitMQ: recebe dados, aplica o domínio e persiste.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .db import Database
from .domain import DomainError, Lancamento, TipoLancamento
from .repository import LancamentoRepository


def _violacao_unicidade(exc: Exception) -> bool:
    return any(c.__name__ in ("IntegrityError", "UniqueViolation") for c in type(exc).__mro__)


class NaoEncontrado(LookupError):
    pass


class Conflito(Exception):
    pass


class LancamentoService:
    def __init__(self, db: Database, repo: LancamentoRepository | None = None) -> None:
        self.db = db
        self.repo = repo or LancamentoRepository()

    def registrar(
        self,
        tipo: TipoLancamento | str,
        valor: Decimal | str | int,
        data_lancamento: date | None = None,
        descricao: str | None = None,
        chave_idempotencia: str | None = None,
        correlation_id: str | None = None,
    ) -> tuple[Lancamento, bool]:
        """Registra um lançamento. Retorna (lançamento, criado_agora).

        Idempotência: se o cliente reenviar a mesma Idempotency-Key (ex.: o
        app caiu antes de receber a resposta), devolvemos o lançamento já
        criado em vez de duplicar o dinheiro no caixa.
        """
        lanc = Lancamento.registrar(tipo, valor, data_lancamento, descricao, chave_idempotencia)
        try:
            with self.db.transaction() as s:
                if chave_idempotencia:
                    existente = self.repo.obter_por_chave(s, chave_idempotencia)
                    if existente:
                        return self._mesmo_pedido(existente, lanc), False
                self.repo.adicionar_com_evento(s, lanc, correlation_id)
        except Exception as exc:
            # Corrida rara: duas requisições com a mesma chave ao mesmo tempo.
            # A UNIQUE do banco barra a segunda; devolvemos o que foi gravado.
            if chave_idempotencia and _violacao_unicidade(exc):
                with self.db.transaction() as s:
                    existente = self.repo.obter_por_chave(s, chave_idempotencia)
                if existente:
                    return self._mesmo_pedido(existente, lanc), False
            raise
        return lanc, True

    @staticmethod
    def _mesmo_pedido(existente: Lancamento, novo: Lancamento) -> Lancamento:
        if (existente.tipo, existente.valor_centavos) != (novo.tipo, novo.valor_centavos):
            raise Conflito("Idempotency-Key já usada com outro conteúdo")
        return existente

    def estornar(
        self, lancamento_id: str, motivo: str | None = None, correlation_id: str | None = None
    ) -> Lancamento:
        try:
            with self.db.transaction() as s:
                original = self.repo.obter(s, lancamento_id)
                if original is None:
                    raise NaoEncontrado("Lançamento não encontrado")
                if self.repo.obter_estorno_de(s, lancamento_id) is not None:
                    raise Conflito("Lançamento já foi estornado")
                try:
                    estorno = original.estornar(motivo)
                except DomainError as exc:
                    raise Conflito(str(exc)) from exc
                self.repo.adicionar_com_evento(s, estorno, correlation_id)
        except Exception as exc:
            if _violacao_unicidade(exc):  # dois estornos simultâneos
                raise Conflito("Lançamento já foi estornado") from exc
            raise
        return estorno

    def obter(self, lancamento_id: str) -> Lancamento:
        with self.db.transaction() as s:
            lanc = self.repo.obter(s, lancamento_id)
        if lanc is None:
            raise NaoEncontrado("Lançamento não encontrado")
        return lanc

    def listar_por_data(self, dia: date, limite: int = 100, offset: int = 0) -> list[Lancamento]:
        with self.db.transaction() as s:
            return self.repo.listar_por_data(s, dia, limite, offset)
