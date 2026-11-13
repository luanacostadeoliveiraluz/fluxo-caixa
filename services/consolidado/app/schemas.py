from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from .domain import SaldoDiario, para_reais


class SaldoDiarioResposta(BaseModel):
    data: date
    total_creditos: Decimal
    total_debitos: Decimal
    saldo: Decimal
    quantidade_lancamentos: int
    atualizado_em: datetime | None

    @staticmethod
    def de(s: SaldoDiario) -> "SaldoDiarioResposta":
        return SaldoDiarioResposta(
            data=s.data,
            total_creditos=para_reais(s.total_creditos_centavos),
            total_debitos=para_reais(s.total_debitos_centavos),
            saldo=para_reais(s.saldo_centavos),
            quantidade_lancamentos=s.quantidade_lancamentos,
            atualizado_em=s.atualizado_em,
        )


class Erro(BaseModel):
    detail: str
