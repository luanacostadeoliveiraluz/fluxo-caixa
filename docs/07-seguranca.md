# 7. Segurança e critérios para consumo dos serviços

## 7.1 O que está implementado no MVP

| Controle | Como |
| --- | --- |
| Autenticação de serviço | Header `X-API-Key`, uma lista de chaves por serviço (variável `API_KEYS`), comparação em tempo constante (`hmac.compare_digest`) contra ataque de temporização |
| Validação de entrada | Pydantic (tipos, tamanhos, casas decimais) + regras de domínio; UUID validado na rota |
| Proteção contra SQL injection | Somente consultas parametrizadas |
| Proteção contra duplicidade | `Idempotency-Key` no POST |
| Imutabilidade / trilha de auditoria | Lançamentos nunca são alterados nem apagados; correção por estorno |
| Contêineres | Usuário sem privilégios (`USER appuser`), imagem slim |
| Isolamento de dados | Banco e usuário de banco separados por serviço |
| Rastreabilidade | `correlation_id` em todos os logs |

## 7.2 Critérios de segurança para consumir (integrar com) os serviços

Quem quiser integrar com as APIs deve atender:

1. **Transporte:** somente HTTPS (TLS 1.2+), terminado no balanceador. HTTP puro é recusado.
2. **Identidade:** cada sistema cliente tem a **sua** credencial. No alvo: **OAuth2 Client Credentials** com JWT emitido pelo IdP corporativo (Cognito / Entra ID / Keycloak), validado no gateway.
3. **Autorização por escopo (menor privilégio):**
   - `lancamentos:escrever`: PDV, ERP (POST e estorno);
   - `lancamentos:ler`: contabilidade;
   - `consolidado:ler`: painéis, relatórios, app do comerciante.
4. **Limite de uso:** rate limit por cliente no gateway (ex.: 100 req/s), com resposta 429.
5. **Idempotência obrigatória** para clientes que fazem retry automático (`Idempotency-Key`).
6. **Rotação de segredos:** chaves e senhas no Secrets Manager / Key Vault, com rotação a cada 90 dias. Nunca em código ou repositório.
7. **Rastreabilidade:** o cliente envia `X-Correlation-ID` para facilitar suporte.

## 7.3 Mensageria e dados

- RabbitMQ com usuário próprio por serviço: o relay só **publica** no exchange; o consumidor só **consome** a sua fila.
- TLS (AMQPS) no broker gerenciado.
- Bancos em subnets privadas, criptografia em repouso (KMS) e em trânsito.
- LGPD: o domínio não guarda dados pessoais. A descrição do lançamento é texto livre, então a orientação de uso é não colocar CPF ou nome de cliente nela.

## 7.4 Proteções de borda (alvo)

WAF (OWASP Top 10, bloqueio por reputação de IP), proteção DDoS (AWS Shield Standard), CORS restrito às origens conhecidas.

## 7.5 Observação sobre as chaves do repositório

As chaves `dev-key-*` do `docker-compose.yml` existem **apenas para rodar localmente**. Em qualquer outro ambiente elas vêm do cofre de segredos.
