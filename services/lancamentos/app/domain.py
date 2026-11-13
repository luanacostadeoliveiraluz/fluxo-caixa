"""Domínio de Lançamentos (bounded context "Lançamentos").

Regras de negócio (invariantes) protegidas aqui, sem depender de banco,
fila ou framework web (arquitetura hexagonal):

1. Todo lançamento é um CRÉDITO (entrada) ou um DÉBITO (saída).
2. O valor é sempre positivo e tem no máximo 2 casas decimais.
   Internamente o dinheiro é guardado em CENTAVOS (inteiro) para evitar
   erros de arredondamento de ponto flutuante.
3. A data do lançamento não pode estar no futuro (fluxo de caixa realizado).
4. Lançamento é imutável: não se edita nem se apaga. Correção = ESTORNO,
   que é um novo lançamento de tipo oposto, apontando para o original.
5. Um lançamento só pode ser estornado uma vez e um estorno não é estornável.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from zoneinfo import ZoneInfo

FUSO_COMERCIANTE = ZoneInfo("America/Sao_Paulo")
VALOR_MAXIMO_CENTAVOS = 100_000_000_00  # R$ 100 milhões por lançamento
TAMANHO_MAXIMO_DESCRICAO = 200


class DomainError(ValueError):
    """Violação de regra de negócio."""


class TipoLancamento(str, Enum):
    CREDITO = "CREDITO"
    DEBITO = "DEBITO"

    def oposto(self) -> "TipoLancamento":
        return TipoLancamento.DEBITO if self is TipoLancamento.CREDITO else TipoLancamento.CREDITO


def hoje() -> date:
    return datetime.now(FUSO_COMERCIANTE).date()


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def para_centavos(valor: Decimal | str | int) -> int:
    """Converte um valor em reais (ex.: '150.75') para centavos (15075)."""
    try:
        dec = Decimal(str(valor))
    except (InvalidOperation, ValueError) as exc:
        raise DomainError("Valor inválido") from exc
    if not dec.is_finite():
        raise DomainError("Valor inválido")
    if dec <= 0:
        raise DomainError("O valor deve ser maior que zero")
    if dec * 100 > VALOR_MAXIMO_CENTAVOS:
        raise DomainError("Valor acima do limite permitido por lançamento")
    if dec != dec.quantize(Decimal("0.01")):
        raise DomainError("O valor deve ter no máximo 2 casas decimais")
    return int(dec * 100)


def para_reais(centavos: int) -> Decimal:
    return (Decimal(centavos) / Decimal(100)).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class Lancamento:
    id: str
    tipo: TipoLancamento
    valor_centavos: int
    data_lancamento: date
    descricao: str | None
    criado_em: datetime
    estorno_de: str | None = None
    chave_idempotencia: str | None = None

    @staticmethod
    def registrar(
        tipo: TipoLancamento | str,
        valor: Decimal | str | int,
        data_lancamento: date | None = None,
        descricao: str | None = None,
        chave_idempotencia: str | None = None,
    ) -> "Lancamento":
        try:
            tipo = TipoLancamento(tipo)
        except ValueError as exc:
            raise DomainError("Tipo deve ser CREDITO ou DEBITO") from exc

        data_lancamento = data_lancamento or hoje()
        if data_lancamento > hoje():
            raise DomainError("A data do lançamento não pode estar no futuro")

        if descricao is not None:
            descricao = descricao.strip() or None
            if descricao and len(descricao) > TAMANHO_MAXIMO_DESCRICAO:
                raise DomainError(
                    f"Descrição deve ter no máximo {TAMANHO_MAXIMO_DESCRICAO} caracteres"
                )

        return Lancamento(
            id=str(uuid.uuid4()),
            tipo=tipo,
            valor_centavos=para_centavos(valor),
            data_lancamento=data_lancamento,
            descricao=descricao,
            criado_em=agora_utc(),
            chave_idempotencia=chave_idempotencia,
        )

    def estornar(self, motivo: str | None = None) -> "Lancamento":
        """Gera o lançamento de estorno (tipo oposto, mesmo valor, data de hoje)."""
        if self.estorno_de is not None:
            raise DomainError("Um estorno não pode ser estornado")
        descricao = f"Estorno de {self.id}" + (f": {motivo.strip()}" if motivo and motivo.strip() else "")
        return replace(
            self,
            id=str(uuid.uuid4()),
            tipo=self.tipo.oposto(),
            data_lancamento=hoje(),
            descricao=descricao[:TAMANHO_MAXIMO_DESCRICAO],
            criado_em=agora_utc(),
            estorno_de=self.id,
            chave_idempotencia=None,
        )

    @property
    def valor(self) -> Decimal:
        return para_reais(self.valor_centavos)


def evento_lancamento_registrado(lanc: Lancamento) -> dict:
    """Contrato do evento de integração publicado para outros contextos.

    Versão 1. Mudanças incompatíveis geram event_version=2 (ver docs/contratos).
    """
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "LancamentoRegistrado",
        "event_version": 1,
        "occurred_at": lanc.criado_em.isoformat(),
        "data": {
            "lancamento_id": lanc.id,
            "tipo": lanc.tipo.value,
            "valor_centavos": lanc.valor_centavos,
            "data_lancamento": lanc.data_lancamento.isoformat(),
            "estorno_de": lanc.estorno_de,
        },
    }
