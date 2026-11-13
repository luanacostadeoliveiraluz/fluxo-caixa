# 2. Refinamento dos requisitos

O enunciado traz dois requisitos de negócio e um não funcional. Abaixo eles estão refinados, com identificador, critério de aceite e onde estão atendidos.

## 2.1 Requisitos funcionais

| ID | Requisito | Critério de aceite | Onde está |
| --- | --- | --- | --- |
| RF01 | Registrar lançamento de crédito ou débito | `POST /api/v1/lancamentos` retorna 201 com o lançamento criado | `lancamentos/app/api.py` |
| RF02 | Validar o lançamento | Tipo inválido, valor ≤ 0, mais de 2 casas ou data futura → 422 | `domain.py` + testes |
| RF03 | Corrigir lançamento sem apagar histórico | `POST /lancamentos/{id}/estorno` cria lançamento oposto; segundo estorno → 409 | `domain.py`, `service.py` |
| RF04 | Consultar lançamento e lançamentos do dia | `GET /lancamentos/{id}` e `GET /lancamentos?data=` | `api.py` |
| RF05 | Evitar lançamento duplicado em reenvio | Mesmo `Idempotency-Key` devolve o mesmo lançamento (200), sem duplicar | `service.py` |
| RF06 | Consolidar o saldo diário | Para cada lançamento, o dia correspondente soma crédito ou débito | `consolidado/app/repository.py` |
| RF07 | Consultar saldo de um dia | `GET /api/v1/consolidado/diario/{data}` com créditos, débitos, saldo e quantidade | `consolidado/app/api.py` |
| RF08 | Consultar saldos de um período | `GET /api/v1/consolidado/diario?inicio=&fim=` (até 93 dias), dias sem movimento = 0 | `service.py` |

## 2.2 Requisitos não funcionais

| ID | Requisito | Meta | Como é atendido | Como é verificado |
| --- | --- | --- | --- | --- |
| RNF01 | **Lançamentos não pode cair se o consolidado cair** (enunciado) | 0 dependência síncrona | Comunicação só por evento assíncrono; Transactional Outbox; fila durável | `scripts/teste_resiliencia.sh`; teste `test_broker_fora_do_ar_...` |
| RNF02 | **Consolidado aguenta 50 req/s com ≤ 5% de perda** (enunciado) | ≥ 50 req/s, perda ≤ 5% | Modelo de leitura pré-calculado (CQRS), leitura por chave primária, cache TTL, 2 réplicas + nginx | `loadtest/carga_consolidado.py` (também no CI) |
| RNF03 | Nenhum lançamento perdido | 0 perda | Outbox na mesma transação; publisher confirms; mensagens persistentes; ack manual | testes do outbox |
| RNF04 | Nenhum lançamento contado duas vezes | 0 duplicidade | Consumidor idempotente por `event_id` | `test_evento_duplicado_...` |
| RNF05 | Consistência do consolidado | Atraso típico < 5 s | Relay a cada 0,5 s + consumo imediato + cache de 2 s | `scripts/smoke_test.py` |
| RNF06 | Latência das APIs | p95 < 200 ms | Leituras por índice/PK; escrita em 1 transação | métrica `http_request_duration_seconds` |
| RNF07 | Disponibilidade (alvo em nuvem) | 99,9% por serviço | Multi-AZ, réplicas, health checks, reinício automático | ver [arquitetura alvo](03-arquitetura-alvo.md) |
| RNF08 | Segurança | Só clientes autenticados | API key (MVP), TLS e OAuth2 no alvo | `test_sem_api_key_retorna_401` |
| RNF09 | Rastreabilidade | Toda operação rastreável ponta a ponta | `X-Correlation-ID` propagado HTTP → evento → logs | logs JSON |
| RNF10 | Auditabilidade | Histórico não pode ser alterado | Lançamento imutável, estorno, sem UPDATE/DELETE de lançamento | domínio |

### Leitura do RNF02 ("perda de no máximo 5%")

Interpretamos "perda" como requisição que **não recebeu resposta 200 em até 2 segundos** (erro, timeout ou recusa). A meta de 5% é um teto. O desenho visa perda próxima de zero, porque cada consulta é uma busca por chave primária em uma tabela pequena (uma linha por dia), normalmente respondida do cache.

**Conta de capacidade:** 50 req/s ÷ 2 réplicas = 25 req/s por réplica. Com cache de 2 s, consultas ao mesmo dia geram no máximo ~1 consulta ao banco a cada 2 s por réplica. O banco quase não é tocado no pico.

## 2.3 Premissas (a validar com o negócio)

1. Um comerciante por instalação (single-tenant). Multiempresa está em [evoluções](08-evolucoes.md).
2. Moeda única: Real (BRL). Valores em centavos.
3. Dia de referência no fuso `America/Sao_Paulo`.
4. Lançamento com data retroativa é permitido (o comerciante esquece de lançar); futuro não (seria previsão, não caixa realizado).
5. Estorno entra na data em que é feito, sem reabrir o dia original (regra contábil comum). Assim, o consolidado de um dia passado só muda se alguém lançar com data retroativa.
6. "Saldo diário consolidado" = resultado do dia (créditos − débitos). Saldo acumulado está em evoluções.

## 2.4 Fora do escopo do MVP

Conciliação bancária, categorias de lançamento, anexos de comprovante, multimoeda, fechamento de caixa com bloqueio de dias.
