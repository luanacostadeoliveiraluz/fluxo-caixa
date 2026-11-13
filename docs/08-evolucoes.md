# 8. O que eu faria com mais tempo (evoluções)

Priorizadas por valor para o comerciante e por risco técnico.

| # | Evolução | Por quê | Esforço |
| --- | --- | --- | --- |
| 1 | OAuth2/JWT com IdP e escopos no gateway | Substitui a API key do MVP; identidade por cliente | M |
| 2 | Multiempresa (`comerciante_id` em lançamentos, eventos e saldo; isolamento por tenant) | Atender vários comerciantes na mesma plataforma | M |
| 3 | Saldo acumulado (saldo final do dia = saldo inicial + resultado do dia) | Pergunta natural do comerciante: "quanto tenho em caixa?" | P |
| 4 | Fechamento de caixa (bloquear lançamentos retroativos em dia fechado) | Controle contábil | P |
| 5 | OpenTelemetry + dashboards Grafana prontos + alertas | Rastreamento distribuído completo | M |
| 6 | Reprocessamento da DLQ com ferramenta administrativa | Hoje a análise é manual pelo painel do RabbitMQ | P |
| 7 | Migrações de banco versionadas (Alembic) | Hoje o schema é criado no boot (`CREATE IF NOT EXISTS`), suficiente para o MVP | P |
| 8 | Infraestrutura como código (Terraform) do desenho AWS | Ambientes reproduzíveis | M |
| 9 | Cache distribuído (Redis) e/ou CDN para consultas de dias fechados | Para dezenas de réplicas | P |
| 10 | Troca do broker para SNS + SQS | Reduz ~35% do custo de nuvem ([custos](05-custos.md)) | P |
| 11 | Reconstrução do consolidado a partir dos eventos (replay) | Recuperação de desastre do read model e novas projeções | M |
| 12 | Categorias e conciliação bancária (Open Finance) | Valor de negócio: DRE simplificada | G |
| 13 | Testes de contrato (consumer-driven, ex.: Pact) | Garantir que mudanças no evento não quebrem o consumidor | P |
| 14 | Testes de carga com k6 no pipeline e testes de caos | Validar RNFs continuamente | P |

P = pequeno, M = médio, G = grande.
