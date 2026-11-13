from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain import (
    DomainError,
    Lancamento,
    TipoLancamento,
    evento_lancamento_registrado,
    hoje,
    para_centavos,
    para_reais,
)


class TestValor:
    @pytest.mark.parametrize(
        "entrada, centavos",
        [("150.75", 15075), ("0.01", 1), (10, 1000), (Decimal("99.9"), 9990), ("150.750", 15075)],
    )
    def test_converte_para_centavos(self, entrada, centavos):
        assert para_centavos(entrada) == centavos

    @pytest.mark.parametrize("entrada", ["0", "-5", "abc", "1.001", "NaN", "Infinity", "1e30"])
    def test_rejeita_valores_invalidos(self, entrada):
        with pytest.raises(DomainError):
            para_centavos(entrada)

    def test_volta_para_reais_com_duas_casas(self):
        assert para_reais(15075) == Decimal("150.75")
        assert str(para_reais(100)) == "1.00"


class TestRegistrar:
    def test_credito_valido(self):
        lanc = Lancamento.registrar("CREDITO", "150.75", descricao="  Venda  ")
        assert lanc.tipo is TipoLancamento.CREDITO
        assert lanc.valor_centavos == 15075
        assert lanc.data_lancamento == hoje()
        assert lanc.descricao == "Venda"
        assert lanc.estorno_de is None

    def test_tipo_invalido(self):
        with pytest.raises(DomainError, match="CREDITO ou DEBITO"):
            Lancamento.registrar("PIX", "10")

    def test_data_futura_nao_permitida(self):
        with pytest.raises(DomainError, match="futuro"):
            Lancamento.registrar("DEBITO", "10", data_lancamento=hoje() + timedelta(days=1))

    def test_data_passada_permitida(self):
        ontem = hoje() - timedelta(days=1)
        assert Lancamento.registrar("DEBITO", "10", data_lancamento=ontem).data_lancamento == ontem

    def test_descricao_muito_longa(self):
        with pytest.raises(DomainError):
            Lancamento.registrar("DEBITO", "10", descricao="x" * 201)


class TestEstorno:
    def test_estorno_inverte_tipo_e_mantem_valor(self):
        original = Lancamento.registrar("CREDITO", "50.00")
        estorno = original.estornar("valor digitado errado")
        assert estorno.tipo is TipoLancamento.DEBITO
        assert estorno.valor_centavos == original.valor_centavos
        assert estorno.estorno_de == original.id
        assert estorno.id != original.id
        assert "valor digitado errado" in estorno.descricao

    def test_estorno_nao_pode_ser_estornado(self):
        estorno = Lancamento.registrar("CREDITO", "50.00").estornar()
        with pytest.raises(DomainError):
            estorno.estornar()


def test_contrato_do_evento():
    lanc = Lancamento.registrar("DEBITO", "12.34")
    evento = evento_lancamento_registrado(lanc)
    assert evento["event_type"] == "LancamentoRegistrado"
    assert evento["event_version"] == 1
    assert evento["data"] == {
        "lancamento_id": lanc.id,
        "tipo": "DEBITO",
        "valor_centavos": 1234,
        "data_lancamento": lanc.data_lancamento.isoformat(),
        "estorno_de": None,
    }
