"""Contratos HTTP (entrada e saída) da API de Lançamentos."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .domain import Lancamento


class NovoLancamento(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"tipo": "CREDITO", "valor": "150.75", "descricao": "Venda balcão"},
                {"tipo": "DEBITO", "valor": "42.00", "data_lancamento": "2026-11-12",
                 "descricao": "Compra de embalagens"},
            ]
        }
    )

    tipo: Literal["CREDITO", "DEBITO"] = Field(description="CREDITO = entrada, DEBITO = saída")
    valor: Decimal = Field(gt=0, max_digits=12, decimal_places=2, description="Valor em reais")
    data_lancamento: date | None = Field(default=None, description="Padrão: hoje (America/Sao_Paulo)")
    descricao: str | None = Field(default=None, max_length=200)


class PedidoEstorno(BaseModel):
    motivo: str | None = Field(default=None, max_length=150)


class LancamentoResposta(BaseModel):
    id: str
    tipo: Literal["CREDITO", "DEBITO"]
    valor: Decimal
    data_lancamento: date
    descricao: str | None
    criado_em: datetime
    estorno_de: str | None

    @staticmethod
    def de(lanc: Lancamento) -> "LancamentoResposta":
        return LancamentoResposta(
            id=lanc.id,
            tipo=lanc.tipo.value,
            valor=lanc.valor,
            data_lancamento=lanc.data_lancamento,
            descricao=lanc.descricao,
            criado_em=lanc.criado_em,
            estorno_de=lanc.estorno_de,
        )


class Erro(BaseModel):
    detail: str
