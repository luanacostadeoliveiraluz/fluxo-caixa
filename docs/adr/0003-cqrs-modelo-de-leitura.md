# ADR-0003: CQRS – modelo de leitura pré-calculado para o consolidado

- **Status:** aceito
- **Data:** 2026-11-13

## Contexto
Calcular o saldo somando todos os lançamentos do dia a cada consulta fica mais lento conforme o volume cresce, e concorre com a escrita no mesmo banco. O requisito é 50 req/s com ≤ 5% de perda.

## Decisão
O Consolidado mantém a tabela `saldo_diario` (uma linha por dia), atualizada **incrementalmente** a cada evento com UPSERT atômico (`total = total + valor`). Consultar é ler uma linha pela chave primária.

## Consequências
- (+) Consulta O(1) e previsível, independente de quantos lançamentos o dia teve.
- (+) A leitura não toca o banco de Lançamentos.
- (+) Soma é comutativa: eventos fora de ordem dão o mesmo resultado.
- (−) Consistência eventual (segundos). Documentado para o negócio.
- (−) Se o read model corromper, precisa ser reconstruído a partir dos eventos/lançamentos (evolução: replay).
