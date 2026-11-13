# 6. Monitoramento e observabilidade

Os três pilares, e o que cada um responde:

| Pilar | Pergunta | Implementação |
| --- | --- | --- |
| **Métricas** | "Está tudo bem agora?" | Prometheus (`/metrics` nas APIs, porta 9100 nos workers) |
| **Logs** | "O que aconteceu com esta operação?" | JSON estruturado no stdout, com `correlation_id` |
| **Rastreamento** | "Por onde esta operação passou?" | `X-Correlation-ID` propagado HTTP → evento → consumidor (MVP); OpenTelemetry no alvo |

## 6.1 Métricas expostas

| Métrica | Serviço | Para que serve |
| --- | --- | --- |
| `http_requests_total{metodo,rota,status}` | APIs | Taxa de requisições e de erros (RED) |
| `http_request_duration_seconds` (histograma) | APIs | Latência p50/p95/p99 |
| `lancamentos_registrados_total{tipo}` | Lançamentos | Volume de negócio |
| `outbox_eventos_pendentes` | Relay | **Principal sinal de saúde da integração**: se cresce, o broker ou o relay estão com problema |
| `consolidado_eventos_total{resultado}` | Consumidor | processado / duplicado / invalido (DLQ) / retry |
| Fila e DLQ (`rabbitmq_queue_messages`) | RabbitMQ | Atraso do consolidado (lag) e mensagens mortas |

## 6.2 Alertas sugeridos (SLOs)

| Alerta | Condição | Severidade |
| --- | --- | --- |
| Erros na API de Lançamentos | taxa de 5xx > 1% por 5 min | Crítico |
| Latência de Lançamentos | p95 > 300 ms por 10 min | Alto |
| Integração parada | `outbox_eventos_pendentes` > 1000 ou crescendo por 5 min | Alto |
| Consolidado atrasado | mensagens na fila `consolidado.lancamentos` > 5000 | Médio |
| Mensagens mortas | DLQ > 0 | Médio (exige análise humana) |
| Perda no Consolidado | (5xx + timeouts) / total > 2% por 5 min (antes de chegar aos 5% do requisito) | Alto |

## 6.3 Exemplo de log

```json
{"ts": "2026-11-13T14:02:11.120+00:00", "nivel": "INFO", "servico": "lancamentos",
 "logger": "lancamentos.api", "msg": "lancamento registrado",
 "correlation_id": "7f3c...", "lancamento_id": "a1b2...", "tipo": "CREDITO"}
```

Com o mesmo `correlation_id` aparece, segundos depois, o log `evento processado` do consumidor do Consolidado. Assim dá para seguir um lançamento de ponta a ponta.

## 6.4 Health checks

- `/health/live`: o processo está vivo (usado para reiniciar o contêiner).
- `/health/ready`: o banco responde (usado pelo balanceador para tirar a réplica de rotação).

## 6.5 Evolução

OpenTelemetry (traces distribuídos com spans HTTP → banco → broker), dashboards prontos no Grafana e alertas no Alertmanager / CloudWatch Alarms.
