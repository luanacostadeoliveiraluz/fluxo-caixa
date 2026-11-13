# ADR-0005: RabbitMQ como broker de eventos

- **Status:** aceito
- **Data:** 2026-11-13

## Opções
| Critério | RabbitMQ | Kafka | SNS + SQS |
| --- | --- | --- | --- |
| Ack por mensagem, DLQ, retry | Nativo | Manual (offsets) | Nativo |
| Roda igual localmente | Sim (1 contêiner) | Pesado (ZooKeeper/KRaft) | Só emulado (LocalStack) |
| Retenção e replay de eventos | Limitado | Excelente | Não |
| Custo no volume do caso | Médio (Amazon MQ) | Alto (MSK) | Muito baixo |
| Operação | Simples | Complexa | Nenhuma |

## Decisão
RabbitMQ: um exchange `topic` (`fluxo-caixa.eventos`), uma fila durável por consumidor (`consolidado.lancamentos`) e uma DLQ (`consolidado.lancamentos.dlq`).

## Consequências
- (+) Semântica de fila de trabalho com ack manual, DLQ e prefetch, exatamente o que o consumidor precisa.
- (+) Novos consumidores (ex.: conciliação) recebem uma fila própria no mesmo exchange, sem mudar o produtor.
- (−) Não guarda histórico para replay. Se isso virar requisito (auditoria, novas projeções), avaliar Kafka.
- (−) É o item mais caro na nuvem. Como a mensageria está atrás de um adaptador (`Publisher`), trocar por SNS+SQS não muda o domínio.
