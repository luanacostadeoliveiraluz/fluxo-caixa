# ADR-0006: Python + FastAPI + PostgreSQL, com arquitetura hexagonal

- **Status:** aceito
- **Data:** 2026-11-13

## Decisão
- **Python 3.12 + FastAPI:** validação de entrada com Pydantic, documentação OpenAPI/Swagger gerada automaticamente (`/docs`), código curto e legível.
- **PostgreSQL:** transações ACID, essenciais para dinheiro e para o outbox; `ON CONFLICT` para o UPSERT idempotente; `FOR UPDATE SKIP LOCKED` para escalar relays.
- **SQL explícito em vez de ORM:** as duas operações críticas (outbox na mesma transação e UPSERT idempotente) ficam visíveis e revisáveis.
- **Dinheiro em centavos (inteiro):** evita erros de ponto flutuante (0,1 + 0,2 ≠ 0,3).
- **Arquitetura hexagonal (portas e adaptadores):** `domain.py` não conhece HTTP, banco ou fila. `service.py` orquestra os casos de uso. `api.py`, `db.py`, `outbox_relay.py` e `consumer.py` são adaptadores.

## Consequências
- (+) Os testes do domínio e dos casos de uso rodam sem infraestrutura (SQLite em arquivo temporário).
- (+) Trocar broker ou banco afeta só o adaptador.
- (−) Python tem menos throughput por núcleo que Go/Java. No volume do enunciado isso não é gargalo, e escala horizontal resolve.
