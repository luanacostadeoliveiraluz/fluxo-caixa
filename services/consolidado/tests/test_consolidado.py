import json
import random
from datetime import date

import pytest

from app.consumer import Resultado, tratar_mensagem
from app.domain import EventoInvalido, LancamentoRegistrado
from app.service import ConsolidadoService, TTLCache

from .conftest import mensagem

DIA = date(2026, 11, 13)


@pytest.fixture
def servico(db):
    return ConsolidadoService(db, cache_ttl_segundos=0)  # sem cache: lê sempre do banco


def processar(servico, msg):
    return tratar_mensagem(servico, json.dumps(msg).encode())


def test_saldo_do_dia_soma_creditos_e_subtrai_debitos(servico):
    processar(servico, mensagem("CREDITO", 15075))
    processar(servico, mensagem("CREDITO", 5000))
    processar(servico, mensagem("DEBITO", 4200))

    saldo = servico.saldo_do_dia(DIA)
    assert saldo.total_creditos_centavos == 20075
    assert saldo.total_debitos_centavos == 4200
    assert saldo.saldo_centavos == 15875
    assert saldo.quantidade_lancamentos == 3


def test_dia_sem_movimento_tem_saldo_zero(servico):
    saldo = servico.saldo_do_dia(date(2026, 1, 1))
    assert (saldo.saldo_centavos, saldo.quantidade_lancamentos) == (0, 0)


def test_evento_duplicado_nao_e_contado_duas_vezes(servico):
    msg = mensagem("CREDITO", 1000)
    assert processar(servico, msg) is Resultado.PROCESSADO
    assert processar(servico, msg) is Resultado.DUPLICADO  # reentrega do broker
    assert servico.saldo_do_dia(DIA).saldo_centavos == 1000


def test_ordem_dos_eventos_nao_altera_o_resultado(db):
    msgs = [mensagem(random.choice(["CREDITO", "DEBITO"]), random.randint(1, 10_000)) for _ in range(50)]
    esperado = sum(m["data"]["valor_centavos"] * (1 if m["data"]["tipo"] == "CREDITO" else -1) for m in msgs)
    random.shuffle(msgs)
    servico = ConsolidadoService(db, 0)
    for m in msgs:
        processar(servico, m)
    assert servico.saldo_do_dia(DIA).saldo_centavos == esperado


def test_estorno_zera_o_efeito_do_lancamento(servico):
    processar(servico, mensagem("CREDITO", 8000))
    processar(servico, mensagem("DEBITO", 8000))  # estorno chega como débito
    assert servico.saldo_do_dia(DIA).saldo_centavos == 0


@pytest.mark.parametrize(
    "corpo",
    [
        b"isto nao e json",
        json.dumps({**mensagem(), "event_type": "Outro"}).encode(),
        json.dumps({**mensagem(), "event_version": 2}).encode(),
        json.dumps(mensagem(valor=-5)).encode(),
        json.dumps(mensagem(tipo="PIX")).encode(),
        json.dumps({"event_id": "x"}).encode(),
    ],
)
def test_mensagem_invalida_vai_para_dlq(servico, corpo):
    assert tratar_mensagem(servico, corpo) is Resultado.INVALIDO


def test_banco_fora_do_ar_pede_nova_tentativa(servico):
    def quebrar(_evento):
        raise ConnectionError("banco indisponível")

    servico.processar = quebrar
    assert processar(servico, mensagem()) is Resultado.TENTAR_DE_NOVO


def test_periodo_preenche_dias_sem_movimento(servico):
    processar(servico, mensagem("CREDITO", 100, dia=date(2026, 11, 1)))
    processar(servico, mensagem("DEBITO", 30, dia=date(2026, 11, 3)))
    dias = servico.saldos_do_periodo(date(2026, 11, 1), date(2026, 11, 3))
    assert [d.saldo_centavos for d in dias] == [100, 0, -30]


def test_periodo_invalido(servico):
    with pytest.raises(ValueError):
        servico.saldos_do_periodo(date(2026, 11, 3), date(2026, 11, 1))
    with pytest.raises(ValueError):
        servico.saldos_do_periodo(date(2026, 1, 1), date(2026, 12, 31))


def test_contrato_do_evento_rejeita_valor_booleano():
    with pytest.raises(EventoInvalido):
        LancamentoRegistrado.de_mensagem(mensagem(valor=True))


class TestCache:
    def test_respeita_ttl(self):
        relogio = [0.0]
        cache = TTLCache(ttl_segundos=2, relogio=lambda: relogio[0])
        chamadas = []
        calcular = lambda: chamadas.append(1) or len(chamadas)  # noqa: E731

        assert cache.obter_ou_calcular("k", calcular) == 1
        assert cache.obter_ou_calcular("k", calcular) == 1  # veio do cache
        relogio[0] = 2.5
        assert cache.obter_ou_calcular("k", calcular) == 2  # expirou
        assert (cache.acertos, cache.falhas) == (1, 2)

    def test_consulta_usa_cache_dentro_do_ttl(self, db):
        servico = ConsolidadoService(db, cache_ttl_segundos=60)
        assert servico.saldo_do_dia(DIA).saldo_centavos == 0
        processar(servico, mensagem("CREDITO", 500))
        assert servico.saldo_do_dia(DIA).saldo_centavos == 0  # ainda no cache
        assert servico.cache.acertos == 1
