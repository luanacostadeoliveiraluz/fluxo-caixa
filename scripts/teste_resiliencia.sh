#!/usr/bin/env bash
# Demonstra o requisito: "o serviço de lançamentos NÃO pode ficar indisponível
# se o consolidado cair". Rode com o docker compose no ar.
set -euo pipefail

L="http://localhost:8001/api/v1/lancamentos"
H=(-H "X-API-Key: dev-key-lancamentos" -H "Content-Type: application/json")

echo "1) Derrubando TODO o serviço de consolidado (API, consumidor e banco)..."
docker compose stop consolidado-api consolidado-consumer consolidado-lb db-consolidado

echo "2) Registrando 5 lançamentos com o consolidado fora do ar..."
for i in 1 2 3 4 5; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$L" "${H[@]}" \
         -d "{\"tipo\":\"CREDITO\",\"valor\":\"10.00\",\"descricao\":\"resiliencia $i\"}")
  echo "   lançamento $i -> HTTP $code"
done

echo "3) Mensagens aguardando na fila (ficam guardadas no RabbitMQ):"
docker compose exec -T rabbitmq rabbitmqctl list_queues name messages | grep consolidado || true

echo "4) Religando o consolidado..."
docker compose start db-consolidado consolidado-consumer consolidado-api consolidado-lb
sleep 15

echo "5) Saldo de hoje depois da recuperação (inclui os R$ 50,00 lançados com ele fora):"
curl -s -H "X-API-Key: dev-key-consolidado" "http://localhost:8002/api/v1/consolidado/diario/$(date +%F)"
echo
