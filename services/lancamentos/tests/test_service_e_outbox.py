import json
from datetime import timedelta

import pytest

from app.domain import DomainError, hoje
from app.outbox_relay import OutboxRelay
from app.service import Conflito, LancamentoService, NaoEncontrado


class PublisherFake:
    def __init__(self, falhar=False):
        self.falhar = falhar
        self.mensagens = []

    def publicar(self, routing_key, evento, correlation_id):
        if self.falhar:
            raise ConnectionError("RabbitMQ fora do ar")
        self.mensagens.append((routing_key, evento, correlation_id))


@pytest.fixture
def servico(db):
    return LancamentoService(db)


def test_registrar_grava_lancamento_e_evento_na_mesma_transacao(db, servico):
    lanc, criado = servico.registrar("CREDITO", "100.00", correlation_id="cid-1")
    assert criado
    assert servico.obter(lanc.id) == lanc
    with db.transaction() as s:
        outbox = s.fetchall("SELECT * FROM outbox")
    assert len(outbox) == 1
    evento = json.loads(outbox[0]["payload"])
    assert evento["data"]["lancamento_id"] == lanc.id
    assert outbox[0]["correlation_id"] == "cid-1"
    assert outbox[0]["publicado_em"] is None


def test_erro_de_dominio_nao_grava_nada(db, servico):
    with pytest.raises(DomainError):
        servico.registrar("CREDITO", "-1")
    with db.transaction() as s:
        assert s.fetchone("SELECT COUNT(*) AS n FROM lancamentos")["n"] == 0
        assert s.fetchone("SELECT COUNT(*) AS n FROM outbox")["n"] == 0


def test_idempotency_key_nao_duplica(servico):
    a, criado_a = servico.registrar("DEBITO", "10.00", chave_idempotencia="pedido-123")
    b, criado_b = servico.registrar("DEBITO", "10.00", chave_idempotencia="pedido-123")
    assert criado_a and not criado_b
    assert a.id == b.id


def test_idempotency_key_com_conteudo_diferente_e_conflito(servico):
    servico.registrar("DEBITO", "10.00", chave_idempotencia="pedido-123")
    with pytest.raises(Conflito):
        servico.registrar("DEBITO", "99.00", chave_idempotencia="pedido-123")


def test_estorno(servico):
    original, _ = servico.registrar("CREDITO", "80.00")
    estorno = servico.estornar(original.id, "cliente devolveu")
    assert estorno.tipo.value == "DEBITO"
    assert estorno.estorno_de == original.id
    with pytest.raises(Conflito, match="já foi estornado"):
        servico.estornar(original.id)
    with pytest.raises(Conflito):
        servico.estornar(estorno.id)


def test_estorno_inexistente(servico):
    with pytest.raises(NaoEncontrado):
        servico.estornar("00000000-0000-0000-0000-000000000000")


def test_listar_por_data(servico):
    ontem = hoje() - timedelta(days=1)
    servico.registrar("CREDITO", "1.00", data_lancamento=ontem)
    servico.registrar("CREDITO", "2.00")
    servico.registrar("DEBITO", "3.00")
    assert len(servico.listar_por_data(hoje())) == 2
    assert [item.valor_centavos for item in servico.listar_por_data(ontem)] == [100]


class TestOutboxRelay:
    def test_publica_pendentes_e_marca_como_publicado(self, db, servico):
        servico.registrar("CREDITO", "1.00", correlation_id="abc")
        servico.registrar("DEBITO", "2.00")
        pub = PublisherFake()
        relay = OutboxRelay(db, pub)

        assert relay.executar_uma_vez() == 2
        assert relay.pendentes() == 0
        assert [m[0] for m in pub.mensagens] == ["lancamento.registrado"] * 2
        assert pub.mensagens[0][2] == "abc"
        assert relay.executar_uma_vez() == 0  # nada é publicado duas vezes

    def test_broker_fora_do_ar_nao_perde_eventos_nem_bloqueia_lancamentos(self, db, servico):
        relay = OutboxRelay(db, PublisherFake(falhar=True))
        servico.registrar("CREDITO", "1.00")
        assert relay.executar_uma_vez() == 0
        # a API continua aceitando lançamentos com o broker fora
        servico.registrar("CREDITO", "2.00")
        assert relay.pendentes() == 2

        # broker volta: tudo é publicado, na ordem de gravação
        pub = PublisherFake()
        relay.publisher = pub
        assert relay.executar_uma_vez() == 2
        valores = [m[1]["data"]["valor_centavos"] for m in pub.mensagens]
        assert valores == [100, 200]
