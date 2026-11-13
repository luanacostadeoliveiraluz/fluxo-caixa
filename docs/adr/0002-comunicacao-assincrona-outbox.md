# ADR-0002: Comunicação assíncrona com Transactional Outbox

- **Status:** aceito
- **Data:** 2026-11-13

## Contexto
O Consolidado precisa saber de cada lançamento. Se Lançamentos chamar o Consolidado por HTTP, a disponibilidade de um passa a depender do outro, o que viola o requisito. Publicar na fila logo depois do commit gera o problema do *dual write*: o banco confirma, a fila está fora, e o evento se perde.

## Decisão
1. Integração **somente por evento** (`LancamentoRegistrado`), via RabbitMQ.
2. **Transactional Outbox:** o lançamento e o evento são gravados na mesma transação do banco de Lançamentos.
3. Um processo separado (**Outbox Relay**) publica os pendentes com *publisher confirms*, mensagens persistentes e `mandatory=true`, e só então marca como publicado.

## Consequências
- (+) Lançamentos não depende de broker nem de Consolidado para responder ao cliente.
- (+) Nenhum evento perdido: se não foi publicado, continua no outbox.
- (+) Ordem preservada por relay (se uma publicação falha, o lote para e recomeça dali).
- (−) Entrega "pelo menos uma vez": pode haver duplicata se o relay cair entre publicar e marcar. Resolvido com idempotência no consumidor (ADR-0007).
- (−) Atraso de até ~0,5 s (intervalo de polling). Evolução possível: CDC com Debezium lendo o WAL.
