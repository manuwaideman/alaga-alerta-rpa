# Alaga Alerta — Robô RPA (Automação)

Robô em **Python** (apenas biblioteca padrão) que monitora a chuva prevista por bairro, cruza com boletim da Defesa Civil/CGE, a tabela Ouro do Big Data e o sensor de nível de água do robô físico, decide o risco de alagamento, **avisa o cidadão** (Telegram) e **publica cada alerta na API central do MVP** (`POST /alertas`), onde ele aparece no site para o cidadão.

## Integrantes

| Nome completo | RM |
|---|---|
| Felipe Capriotti | RM98460 |
| Gustavo Kawamura | RM99679 |
| Manoella Herrerias Waideman | RM98906 |
| Victor Hugo Andrade | RM550996 |

## Ficha Técnica do MVP (parte de Automação)
| Campo | Alaga Alerta |
|---|---|
| Nome do produto | Alaga Alerta |
| Cidadão e território | Moradores e motoristas de bairros com histórico de alagamento (ex.: São Paulo) |
| Problema | Alertas de chuva são genéricos e chegam tarde para quem precisa decidir sair ou desviar |
| Papel do RPA | Monitorar, decidir e alertar automaticamente, a cada 30 min, sem operação manual |
| Fontes de dados | Open-Meteo, boletins CGE/Defesa Civil, tabela Ouro (Big Data), leituras do ESP32 |
| ODS conectados | 11 (cidades sustentáveis) e 13 (ação climática); secundários: 3 e 9 |
| URL do MVP / repositório principal | [preencher] |
| Vídeo demonstrativo | [preencher] |

## Como rodar (3 comandos, nada a instalar)
Requer Python 3.10 ou superior.
```bash
python run.py --simulado --agora 2026-11-17T14:00     # demonstração com previsão simulada
python -m unittest discover -s tests -v               # 37 testes
python run.py                                          # produção: usa o Open-Meteo de verdade
```
Windows: use `python` (ou `py`) no lugar de `python3`. O script `./demo.sh` (Git Bash/Linux/Mac) roda toda a demonstração do vídeo.

**Opções:** `--simulado`, `--agora AAAA-MM-DDTHH:MM`, `--db`, `--boletim`, `--ouro`, `--open-meteo-url`, `--mvp-url`.
**Código de saída:** `0` tudo certo; `2` terminou com falhas parciais (já registradas no log). Útil para o agendador.

### Telegram (alerta real)
1. No Telegram, fale com `@BotFather`, crie um bot e copie o token.
2. Mande uma mensagem ao bot e descubra o seu chat id (ex.: `https://api.telegram.org/bot<TOKEN>/getUpdates`).
3. Defina as variáveis (nunca no código): `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` (veja `.env.example`).

Sem as variáveis o canal é **simulado** (a mensagem não sai, mas todo o resto funciona e o log informa `canal=simulado`). WhatsApp não foi implementado: exige API paga; o ponto de troca é `src/alaga_rpa/notificador.py`.

### Agendamento
- Linux/Mac: `*/30 * * * * cd /caminho/alaga-alerta-rpa && python3 run.py >> logs/cron.out 2>&1`
- Windows: Agendador de Tarefas, repetir a cada 30 minutos, executando `python run.py`.

## Integração com o Alaga Alerta (MVP)
```
Open-Meteo ──────┐
Boletim CGE ─────┤
Ouro (Big Data) ─┼─► ROBÔ RPA ──POST /alertas──► API central do MVP ──► site (mapa + "Alertas ativos")
ESP32 ──POST /leituras──► API central ──GET /leituras──┘   └──► Telegram (cidadão)
```

**Como ligar:** defina no ambiente (nunca no código) a URL e a chave da API central:
```bash
# Mac/Linux/Git Bash
export MVP_URL=https://URL-DO-MVP MVP_API_KEY=chave-do-mvp
# Windows PowerShell
$env:MVP_URL="https://URL-DO-MVP"; $env:MVP_API_KEY="chave-do-mvp"
python run.py --simulado --agora 2026-11-17T14:00
```
Sem essas variáveis o robô funciona como antes (só banco local e `mock_api.py`).

| Direção | O quê | Contrato |
|---|---|---|
| Entrada | Leituras do robô físico (Maker Lab) que o ESP32 enviou à API central | `GET /leituras` do MVP (`bairro_id`, `classificacao`, `medido_em`); `perigo` é gatilho de alerta |
| Entrada | Ouro do Big Data | CSV `bairro,hora,risco` (exportação agendada); só vale a linha da janela da previsão |
| Entrada | Boletim CGE/Defesa Civil | CSV `bairro,data_hora,estado`; boletim com mais de 6 h é ignorado |
| **Saída** | Alerta para o cidadão no site | `POST /alertas` com `X-API-Key`: `{bairro_id, nivel (atencao/alto), mensagem, criado_em, valido_ate, origem: "rpa", canais}` |
| Saída | Alerta no celular | Telegram |
| Saída | Auditoria | Tabela local `alertas` (com `publicado_mvp` e `id_mvp`), tabela `execucoes` e logs |

Tradução de vocabulário: `perigo` (RPA) vira `alto` (MVP); o nome do bairro vira o `bairro_id` do MVP (`BAIRRO_ID` em `src/alaga_rpa/config.py`). Se o MVP estiver fora do ar ou recusar a chave, o alerta fica com `publicado_mvp = 0` e é republicado na próxima execução (evidência 11). A API central é idempotente: o mesmo alerta ainda ativo não é duplicado no site.

Evidências: `docs/evidencias/10_integracao_mvp_real.txt` (execução contra a API real do MVP) e `assets/mvp_alertas_do_rpa.png` (os alertas do robô no site).

`src/mock_api.py` continua disponível como API mínima de demonstração offline (`GET /alertas`, `POST /leituras` no banco local), útil para testar sem o MVP no ar.

## Requisitos da disciplina e onde estão
| # | Etapa obrigatória | Onde |
|---|---|---|
| 01 | Mapeamento do processo | `docs/PDD.md` e `docs/bpmn/alaga_rpa.bpmn` / `.png` |
| 02 | Desenvolvimento em Python | `src/alaga_rpa/` (`robo.py` orquestra; `coleta.py`, `decisao.py`, `notificador.py`) |
| 03 | Decisão + repetição sobre coleções | Repetição: `for bairro in BAIRROS` (`robo.py`), leitura linha a linha dos CSVs e das leituras do MVP; decisão: `decisao.py` (limiares e maior nível entre as fontes) |
| 04 | Exceções: API fora, arquivo inválido/ausente, duplicados, dados velhos | `coleta.py`, `robo.py`, `mvp.py`; evidências 03, 05, 06, 07, 08, 11 |
| 05 | Logs com data/hora, itens, sucessos, falhas e erros, sem dados sensíveis | `logs/` e tabela `execucoes`; segredos mascarados e testados |
| 06 | Resultado consumido por outro componente | `POST /alertas` na API central; o site do MVP mostra (evidência 10 e `assets/mvp_alertas_do_rpa.png`) |
| 07 | Testes de sucesso, decisão e falha | `tests/test_rpa.py`, `docs/testes.md` |
| 08 | Repositório público estruturado | Esta estrutura + README |

## Estrutura
```
README.md  run.py  demo.sh  requirements.txt  .env.example  .gitignore
src/alaga_rpa/   config.py  util.py  db.py  coleta.py  decisao.py  notificador.py  mvp.py  robo.py  __main__.py
src/mock_api.py  API de demonstração da integração
amostras/        boletim_cge.csv  ouro_risco_bairro_hora.csv  previsao_simulada.json  boletim_cge_invalido.csv
docs/            PDD.md  testes.md  bpmn/  evidencias/
assets/          bpmn_alaga_rpa.png  mvp_alertas_do_rpa.png
logs/            amostras de log sem dados sensíveis
tests/           test_rpa.py  test_integracao_mvp.py
```

## Dados simulados (justificativa)
`amostras/` contém dados **simulados**, gerados à mão, para a demonstração ser reproduzível e determinística. A chuva simulada cria três situações de propósito (atenção, perigo e normal), e o boletim e o Ouro cobrem os casos de elevação do risco. Em produção (`python run.py`) a chuva vem do Open-Meteo. O CGE não oferece API oficial: o boletim entra como CSV (exportado por uma etapa de coleta ou preenchido a partir do boletim público).

## LGPD, segurança e acessibilidade
- Nenhum dado pessoal de cidadão é coletado ou guardado pelo robô.
- Credenciais só por variável de ambiente (`TELEGRAM_*`, `MVP_API_KEY`); `.env` ignorado pelo Git; token e chave nunca aparecem em log nem em exceção (testes automatizados).
- Mensagens em linguagem simples, curtas, com o nível em texto (não só cor) e a orientação do que fazer.

## Limitações conhecidas
- Os bairros monitorados pelo robô precisam existir na API central (`GET /bairros`); para incluir um bairro, adicione-o em `BAIRROS` e `BAIRRO_ID`.
- Os limiares (15 mm e 30 mm em 3 h) são pontos de partida; calibre com os dados históricos da Ouro.
- Mensagens vão a um único chat configurado; um cadastro de assinantes por bairro é o próximo passo.
