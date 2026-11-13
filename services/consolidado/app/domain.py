"""Domínio do Consolidado Diário (bounded context "Consolidado").

Este contexto NÃO é dono dos lançamentos: ele mantém um modelo de leitura
(read model / projeção CQRS) com o saldo de cada dia, alimentado pelos
eventos LancamentoRegistrado.

Regras:
- saldo do dia = total de créditos - total de débitos daquele dia;
- cada evento é aplicado no máximo uma vez (idempotência por event_id);
- a soma é comutativa: eventos fora de ordem geram o mesmo resultado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


class EventoInvalido(ValueError):
    """Mensagem que nunca poderá ser processada (vai para a DLQ)."""


@dataclass(frozen=True)
class LancamentoRegistrado:
    event_id: str
    lancamento_id: str
    tipo: str
    valor_centavos: int
    data_lancamento: date

    @property
    def credito_centavos(self) -> int:
        return self.valor_centavos if self.tipo == "CREDITO" else 0

    @property
    def debito_centavos(self) -> int:
        return self.valor_centavos if self.tipo == "DEBITO" else 0

    @staticmethod
    def de_mensagem(msg: dict) -> "LancamentoRegistrado":
        """Valida e traduz o contrato do evento (camada anticorrupção)."""
        try:
            if msg.get("event_type") != "LancamentoRegistrado":
                raise EventoInvalido(f"tipo de evento não suportado: {msg.get('event_type')}")
            if msg.get("event_version") != 1:
                raise EventoInvalido(f"versão não suportada: {msg.get('event_version')}")
            dados = msg["data"]
            tipo = dados["tipo"]
            valor = dados["valor_centavos"]
            if tipo not in ("CREDITO", "DEBITO"):
                raise EventoInvalido(f"tipo de lançamento inválido: {tipo}")
            if not isinstance(valor, int) or isinstance(valor, bool) or valor <= 0:
                raise EventoInvalido("valor_centavos deve ser inteiro positivo")
            return LancamentoRegistrado(
                event_id=str(msg["event_id"]),
                lancamento_id=str(dados["lancamento_id"]),
                tipo=tipo,
                valor_centavos=valor,
                data_lancamento=date.fromisoformat(dados["data_lancamento"]),
            )
        except EventoInvalido:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise EventoInvalido(f"evento malformado: {exc}") from exc


@dataclass(frozen=True)
class SaldoDiario:
    data: date
    total_creditos_centavos: int = 0
    total_debitos_centavos: int = 0
    quantidade_lancamentos: int = 0
    atualizado_em: datetime | None = None

    @property
    def saldo_centavos(self) -> int:
        return self.total_creditos_centavos - self.total_debitos_centavos


def para_reais(centavos: int) -> Decimal:
    return (Decimal(centavos) / Decimal(100)).quantize(Decimal("0.01"))
