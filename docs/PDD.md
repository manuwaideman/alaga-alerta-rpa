# PDD — Documento de Definição do Processo

**Processo:** Monitorar risco de alagamento por bairro e alertar o cidadão
**Produto:** Alaga Alerta (CitizenTech: tecnologia a serviço do cidadão)
**Automação:** `python run.py` (agendado a cada 30 minutos)
**Diagrama:** `docs/bpmn/alaga_rpa.bpmn` (editável em bpmn.io) e `docs/bpmn/alaga_rpa.png`

## 1. Objetivo e benefício
Hoje o cidadão recebe avisos de chuva genéricos e tardios. O robô faz, sozinho e sem fila de trabalho manual, o que uma pessoa teria de fazer a cada meia hora: consultar chuva por bairro, cruzar com boletins e sensores, decidir o risco e avisar quem pode ser afetado, com orientação do que fazer.

## 2. Início, fim e frequência
- **Início:** agendador dispara `run.py` (cron / Agendador de Tarefas), a cada 30 min.
- **Fim:** resumo da execução gravado no log e na tabela `execucoes`.

## 3. Entradas
| Entrada | Origem | Formato | Se faltar |
|---|---|---|---|
| Chuva prevista (mm nas próximas 3 h) | Open-Meteo (API pública) | JSON/HTTP | 3 tentativas, depois cache (até 6 h), depois registra falha e decide com as outras fontes |
| Boletim CGE/Defesa Civil | `amostras/boletim_cge.csv` | CSV: `bairro,data_hora,estado` | Registra aviso/erro e segue sem a fonte; boletim com mais de 6 h é descartado |
| Risco por bairro e hora (Ouro) | Exportação do Big Data | CSV: `bairro,hora,risco` | Idem; só vale a linha dentro da janela da previsão |
| Leitura do nível de água | Robô físico (ESP32) grava na API central (`POST /leituras`); o RPA lê `GET /leituras` do MVP (e a tabela local `leituras`) | JSON/HTTP | Sem leitura válida (60 min) a fonte é ignorada; MVP fora do ar: erro registrado e segue com as leituras locais |

## 4. Etapas (resumo do BPMN)
1. Carregar configuração e abrir o log.
2. Reenviar alertas que ficaram `pendente` (Telegram) e republicar no MVP os que não chegaram lá.
3. Ler boletim, Ouro e leituras de sensor (validando formato).
4. **Repetição:** para cada bairro, consultar a chuva prevista.
5. **Decisão:** calcular o risco final.
6. Gravar o alerta na tabela `alertas` (ignora duplicado).
7. Enviar a mensagem (Telegram) com retentativas.
8. Publicar o alerta na API central do MVP (`POST /alertas`) com retentativas; se falhar, republicar na próxima execução.
9. Gravar auditoria e resumo.

## 5. Regras de negócio e decisões
**Chuva acumulada na janela (padrão 3 h):** `< 15 mm` normal; `15 a < 30 mm` atenção; `>= 30 mm` perigo.
**Risco final = o MAIOR nível entre quatro fontes:** chuva prevista, boletim, Ouro e sensor. Cada fonte acima de "normal" entra no campo `motivo` do alerta, para que o cidadão e a auditoria saibam o porquê.

| Decisão | Resultado |
|---|---|
| Risco final = normal | Não gera alerta; registra "sem alerta" |
| Já existe alerta (mesmo bairro, nível e hora de referência) | Ignora e registra "duplicado" |
| Subiu de atenção para perigo | Novo alerta (nível diferente) |
| Envio falhou após 3 tentativas | Alerta fica `pendente` e é reenviado na próxima execução |
| Boletim ou Ouro fora da validade | Linha descartada e registrada no log (dado velho não decide) |
| Publicação no MVP falhou | Alerta fica com `publicado_mvp = 0` e é republicado na próxima execução |

## 6. Exceções e recuperação
| Exceção | Tratamento | Onde está provado |
|---|---|---|
| API de clima fora do ar | Retentativa com espera exponencial; cache de até 6 h; sem cache, erro registrado e decisão com as demais fontes | evidências 05 e 06; testes `test_api_fora_*` |
| Arquivo inválido (cabeçalho errado) | `ArquivoInvalido`: erro no log, segue sem a fonte | evidência 07; `test_arquivo_invalido_*` |
| Arquivo ausente | Aviso no log, contado como falha, segue | evidência 07; `test_arquivo_ausente_*` |
| Linhas inválidas ou duplicadas no CSV | Descartadas e contadas no log | `test_linhas_invalidas_e_duplicadas_do_csv` |
| Dados duplicados (mesmo alerta) | `UNIQUE(bairro, nivel, hora_ref)` + `INSERT OR IGNORE` | evidência 03; `test_dados_duplicados_*` |
| Telegram fora do ar | Retentativas, `pendente`, reenvio posterior | evidência 08; `test_envio_falha_*` |
| API central do MVP fora do ar ou chave recusada | 3 tentativas; erro sem expor a chave; republica na próxima execução | evidência 11; `test_mvp_fora_*`, `test_chave_recusada_*` |
| Dados velhos (boletim de ontem, Ouro de outro horário) | Descartados e registrados | `test_boletim_de_ontem_*`, `test_ouro_de_outro_horario_*` |
| Falha parcial | Código de saída 2 (o agendador percebe) | evidências 05, 07, 08 e 11 |

## 7. Saídas
- Alerta publicado na API central do MVP (`POST /alertas`) e exibido no site, no mapa e na lista "Alertas ativos" (evidência 10).
- Tabela local `alertas` (auditoria, com `publicado_mvp` e `id_mvp`).
- Mensagem ao cidadão (Telegram) com nível, motivo e orientação.
- Log em `logs/rpa_AAAA-MM-DD.log` e tabela `execucoes` (auditoria).

## 8. Segurança e LGPD
- O robô não coleta nem guarda dados pessoais de cidadãos: só bairro, chuva, nível de risco e leituras de sensor.
- Token do Telegram, chat id e chave da API do MVP vêm de variáveis de ambiente (ou `.env`, que está no `.gitignore`).
- O log mascara o chat id (`***321`) e nunca grava o token nem a URL do Telegram (que o contém); há testes que verificam isso.
- Para assinantes reais no futuro: base legal/consentimento, minimização e canal de descadastro.
