# 5. Estimativa de custos (infraestrutura e licenças)

## 5.1 Licenças

**R$ 0.** Todos os componentes são open source: Python, FastAPI, PostgreSQL, RabbitMQ, nginx e Prometheus. Em nuvem paga-se só o serviço gerenciado (infraestrutura), não a licença.

## 5.2 Infraestrutura em nuvem (AWS)

> **Atenção:** preços de referência **on-demand da região us-east-1**, levantados em novembro de 2026 em fontes públicas (links abaixo). A região de São Paulo (sa-east-1) costuma ser mais cara; antes de qualquer decisão, refazer a conta na [AWS Pricing Calculator](https://calculator.aws/). Itens marcados com "≈" são ordens de grandeza, não cotação.

Premissas: 730 horas/mês, ARM (Graviton), volume do enunciado (pico de 50 req/s de leitura; escrita bem menor).

| Componente | Configuração | Conta | US$/mês |
| --- | --- | --- | --- |
| Lançamentos API | 2 tarefas Fargate, 0,5 vCPU / 1 GB | 2 × (0,5 × 0,03238 + 1 × 0,00356) × 730 | 29 |
| Consolidado API | 2 tarefas (base) | idem | 29 |
| Relay + Consumidor | 2 tarefas, 0,25 vCPU / 0,5 GB | 2 × (0,25 × 0,03238 + 0,5 × 0,00356) × 730 | 14 |
| PostgreSQL Lançamentos | RDS db.t4g.micro **Multi-AZ** | 2 × 0,016 × 730 | 23 |
| PostgreSQL Consolidado | RDS db.t4g.micro **Multi-AZ** | 2 × 0,016 × 730 | 23 |
| RabbitMQ | Amazon MQ mq.m7g.medium, instância única | 0,117 × 730 | 85 |
| Balanceador, armazenamento, logs, segredos | ALB, 2 × 20 GB, CloudWatch, Secrets Manager | ≈ | 40 |
| **Total cenário MVP** | | | **≈ 245** |
| Alta disponibilidade do broker | Amazon MQ em cluster de 3 nós (no lugar da instância única) | 0,351 × 730 − 85 | + 171 |
| **Total cenário produção HA** | | | **≈ 415** |

### Onde está o maior custo e como reduzir

O **broker é ~35% da conta**. Para o volume deste comerciante, duas alternativas mais baratas:

1. **Amazon SNS + SQS** (cobrança por mensagem): para alguns milhões de mensagens/mês, fica em poucos dólares. Custo: troca do adaptador de mensageria (o domínio não muda, por causa da arquitetura hexagonal).
2. **RabbitMQ em contêiner** no próprio ECS, com volume persistente: mais barato, mas a equipe passa a operar o broker.

Mantivemos RabbitMQ no desenho porque é o que roda igual no ambiente local e na nuvem. A troca para SQS está registrada no [ADR-0005](adr/0005-broker-rabbitmq.md) como evolução de custo.

### Custo do pico

O pico de 50 req/s cabe nas 2 réplicas base. O auto scaling até 6 réplicas no Consolidado acrescentaria ≈ US$ 14,40 por réplica por mês **se** ficassem ligadas o mês inteiro; como o pico dura horas, o custo real é proporcional (Fargate cobra por segundo).

## 5.3 Fontes dos preços

- Fargate (ARM, us-east-1): US$ 0,03238 por vCPU-hora e US$ 0,00356 por GB-hora. [Vantage: AWS Fargate Pricing Explained](https://www.vantage.sh/blog/fargate-pricing)
- RDS db.t4g.micro: a partir de US$ 0,016/hora. [Vantage Instances: db.t4g.micro](https://instances.vantage.sh/aws/rds/db.t4g.micro)
- Amazon MQ for RabbitMQ mq.m7g.medium: ≈ US$ 0,117/hora (instância única) e ≈ US$ 0,351/hora (cluster), us-east-1. [CloudBurn: Amazon MQ Pricing](https://cloudburn.io/blog/amazon-mq-pricing)
- Página oficial: [Amazon MQ pricing](https://aws.amazon.com/amazon-mq/pricing/), [AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/), [Amazon RDS for PostgreSQL pricing](https://aws.amazon.com/rds/postgresql/pricing/)
