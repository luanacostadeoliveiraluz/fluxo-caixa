# ADR-0001: Dois microsserviços (Lançamentos e Consolidado)

- **Status:** aceito
- **Data:** 2026-11-13

## Contexto
O enunciado exige que o controle de lançamentos continue disponível mesmo se o consolidado cair, e que o consolidado aguente picos de 50 req/s. São duas cargas com perfis opostos: escrita crítica e consistente, leitura em volume e tolerante a atraso.

## Opções
1. **Monolito** (um processo, um banco): mais simples, mas uma falha ou um pico de leitura derruba também a escrita.
2. **Monolito modular** (módulos separados, um deploy): isola o código, não isola a falha nem a escala.
3. **Dois microsserviços**, cada um com seu banco.
4. **Serverless** (funções + fila gerenciada): ótimo para custo, mas prende a um provedor e complica a execução local exigida pelo desafio.

## Decisão
Opção 3. Os limites seguem os bounded contexts (Lançamentos e Consolidado), não camadas técnicas.

## Consequências
- (+) Isolamento de falha e escala independente, que são exatamente os requisitos não funcionais do enunciado.
- (+) Deploy independente.
- (−) Mais peças para operar (broker, dois bancos). Mitigado com docker compose local e serviços gerenciados na nuvem.
- (−) Consistência eventual entre os dois. Aceitável: o saldo pode atrasar segundos (ver ADR-0003).
