# ADR-0004: Cache TTL em memória nas réplicas do Consolidado

- **Status:** aceito
- **Data:** 2026-11-13

## Contexto
No pico, a maioria das consultas é sobre o mesmo dia (hoje). Mesmo sendo leituras por chave primária, 50 req/s × N réplicas chegando ao banco é desnecessário.

## Opções
1. Sem cache.
2. Cache em memória por réplica com TTL curto.
3. Redis compartilhado.

## Decisão
Opção 2, TTL padrão de 2 s (`CACHE_TTL_SEGUNDOS`), e `Cache-Control: private, max-age` na resposta.

## Consequências
- (+) Zero infraestrutura nova; o banco recebe no máximo ~1 consulta por dia consultado a cada 2 s por réplica.
- (−) Atraso adicional de até 2 s no saldo. Aceitável, porque o consolidado já é eventualmente consistente.
- (−) Cada réplica tem o seu cache. Com dezenas de réplicas, migrar para Redis (opção 3).
