# ADR-0007: Idempotência ponta a ponta

- **Status:** aceito
- **Data:** 2026-11-13

## Contexto
Em sistemas distribuídos, mensagens e requisições podem chegar repetidas: o cliente reenvia por timeout, o relay republica após uma queda, o broker reentrega após um nack. Em fluxo de caixa, contar duas vezes significa saldo errado.

## Decisão
1. **Na entrada (cliente → Lançamentos):** header `Idempotency-Key`, guardado com `UNIQUE` no banco. Repetição com o mesmo conteúdo devolve o lançamento original (HTTP 200). Com conteúdo diferente, HTTP 409.
2. **Na integração (broker → Consolidado):** tabela `eventos_processados` com `event_id` como chave primária, gravada na **mesma transação** do UPSERT do saldo. Evento repetido não altera o saldo.
3. **No domínio:** estorno único garantido por `UNIQUE (estorno_de)`.

## Consequências
- (+) Entrega "pelo menos uma vez" se torna, na prática, "efeito exatamente uma vez".
- (−) A tabela `eventos_processados` cresce. Evolução: expurgo de eventos com mais de N dias (a janela de reentrega real é de minutos).
