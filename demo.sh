#!/usr/bin/env bash
# Roteiro de demonstração (vídeo): sobe a API de demonstração, envia leitura do sensor,
# roda o robô, mostra o que o MVP lê e depois simula API de clima fora do ar.
set -e
cd "$(dirname "$0")"
export PYTHONPATH=src ALAGA_DB=data/demo.db ESPERA_BASE_S=0.3
rm -f data/demo.db data/demo_mvp.db; rm -rf data/cache
python3 src/mock_api.py --db data/demo.db --porta 8000 >/dev/null 2>&1 & API=$!
trap "kill $API 2>/dev/null" EXIT
sleep 1
echo -e "\n### 1) Sensor do robô físico envia leitura 'perigo' para a API central"
curl -s -X POST localhost:8000/leituras -H 'Content-Type: application/json' \
  -d '{"sensor_id":"ESP32-01","bairro":"Jabaquara","nivel_cm":82,"classificacao":"perigo","lido_em":"2026-11-17T13:50:00-03:00"}'
echo -e "\n\n### 2) Execução ponta a ponta (previsão simulada)"
python3 run.py --simulado --agora 2026-11-17T14:00 || true
echo -e "\n### 3) O que o MVP lê: GET /alertas"
curl -s localhost:8000/alertas | python3 -m json.tool | head -30
echo -e "\n### 4) Mesma execução de novo: sem duplicar"
python3 run.py --simulado --agora 2026-11-17T14:00 | tail -2 || true
echo -e "\n### 5) FALHA: API de clima fora do ar (usa cache de 30 min)"
python3 run.py --agora 2026-11-17T14:30 --open-meteo-url http://127.0.0.1:9/ | tail -4 || true
echo -e "\n### 6) FALHA: boletim inválido e Ouro ausente"
python3 run.py --simulado --agora 2026-11-17T15:00 --boletim amostras/boletim_cge_invalido.csv --ouro amostras/nao_existe.csv | grep -E "ERROR|WARNING|Fim" || true

# 7) Integração com a API central do MVP (só roda se MVP_URL e MVP_API_KEY estiverem definidas)
if [ -n "$MVP_URL" ] && [ -n "$MVP_API_KEY" ]; then
  echo -e "\n### 7) Integração real: ESP32 grava no MVP, robô publica os alertas no MVP"
  curl -s -X POST "$MVP_URL/leituras" -H "X-API-Key: $MVP_API_KEY" -H 'Content-Type: application/json' \
    -d '{"sensor_id":"ESP32-01","bairro_id":"jabaquara","nivel_cm":82,"classificacao":"perigo","medido_em":"2026-11-17T13:50:00-03:00"}'
  echo
  ALAGA_DB=data/demo_mvp.db python3 run.py --simulado --agora 2026-11-17T14:00 | grep -E "publicado|Fim" || true
  echo -e "\nAlertas ativos no MVP:"
  curl -s "$MVP_URL/alertas?ativos=true" | python3 -m json.tool | grep -E '"bairro_nome"|"nivel"' || true
else
  echo -e "\n### 7) (pulado) Defina MVP_URL e MVP_API_KEY para demonstrar a integração com a API central do MVP"
fi
