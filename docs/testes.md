# Registro de testes

Comando: `python -m unittest discover -s tests -v` (saída completa em `docs/evidencias/09_testes_unittest.txt`).
Resultado: **37 testes, todos aprovados** (24 do robô + 13 da integração com o MVP e da validade dos dados). Os testes não dependem de internet nem de credenciais (provedores e notificador são substituídos por versões falsas).

## Sucesso
| Teste | O que prova |
|---|---|
| `test_chuva_forte_gera_alerta_perigo_enviado` | Chuva de 35 mm gera alerta `perigo`, gravado, enviado, com orientação e telefone 199 |
| `test_leitura_csv_boletim_valida` | Boletim lido; "Atenção" e "Alerta" mapeados para os níveis internos |
| `test_open_meteo_soma_janela` | Soma exata das 3 horas da janela (14h, 15h, 16h), ignorando 17h |
| `test_leitura_entra_pela_api_e_alerta_sai_pela_api` | Integração: `POST /leituras` na API, robô roda, `GET /alertas` devolve o alerta |

## Decisão
| Teste | O que prova |
|---|---|
| `test_limiares_da_chuva` | Bordas 14,9 / 15 / 29,9 / 30 mm |
| `test_vale_o_maior_nivel_entre_as_fontes` | Maior nível entre as fontes e motivos registrados |
| `test_sensor_perigo_dispara_alerta_mesmo_sem_chuva` | Leitura "perigo" do robô físico é gatilho de alerta |
| `test_leitura_velha_e_ignorada` | Leitura com mais de 60 min não conta |
| `test_tudo_normal_nao_alerta` | Sem risco, sem alerta |
| `test_boletim_eleva_risco` | Boletim "Atenção" gera alerta mesmo com pouca chuva |

## Falha
| Teste | O que prova |
|---|---|
| `test_retry_ate_funcionar` / `test_retry_esgotado_relanca_erro` | 3 tentativas; esgotadas, o erro sobe (não é engolido) |
| `test_api_fora_usa_cache_valido` | API fora do ar, cache de 1 h usado |
| `test_cache_vencido_nao_e_usado` | Cache de 7 h rejeitado |
| `test_api_fora_sem_cache_registra_falha_e_continua` | Falhas contadas e logadas em ERROR; robô processa todos os bairros |
| `test_open_meteo_inacessivel_vira_erro_coleta` | Erro de rede vira `ErroColeta` tratável |
| `test_arquivo_ausente_nao_derruba_o_robo` | Arquivo ausente: aviso, contado como falha, robô segue |
| `test_arquivo_invalido_e_registrado_como_erro` | Cabeçalho errado: `ArquivoInvalido`, erro no log |
| `test_linhas_invalidas_e_duplicadas_do_csv` | 4 linhas lidas: 1 duplicada, 2 inválidas, 1 aproveitada |
| `test_dados_duplicados_nao_duplicam_alerta` | 2ª execução não cria nem reenvia alerta |
| `test_envio_falha_fica_pendente_e_e_reenviado` | Telegram fora: `pendente`; próxima execução reenvia |
| `test_log_nao_vaza_segredos` / `test_notificador_nao_expoe_token_no_erro` | Token e chat id não aparecem em log nem em exceção |
| `test_modo_simulado_sem_credenciais` | Sem credenciais o canal é simulado |

## Integração com o MVP e validade dos dados (`tests/test_integracao_mvp.py`)
| Tipo | Teste | O que prova |
|---|---|---|
| Sucesso | `test_alerta_e_publicado_no_contrato_do_mvp` | Alerta vai para `POST /alertas` no formato do MVP (`perigo` vira `alto`, `bairro_id`, origem `rpa`, chave no cabeçalho) e fica marcado `publicado_mvp = 1` |
| Decisão | `test_leitura_de_perigo_vinda_do_mvp_dispara_alerta` | Leitura `perigo` do ESP32 lida da API central dispara alerta; leitura de ontem e bairro não monitorado são ignorados |
| Decisão | `test_boletim_de_ontem_nao_gera_alerta` / `test_boletim_recente_continua_valendo` | Boletim com mais de 6 h não decide; boletim recente decide |
| Decisão | `test_ouro_de_outro_horario_e_ignorada` | Só vale a linha da Ouro dentro da janela da previsão |
| Falha | `test_mvp_fora_do_ar_fica_pendente_e_e_republicado` | MVP fora do ar: alerta não se perde, é republicado na execução seguinte sem duplicar |
| Falha | `test_leituras_do_mvp_indisponiveis_nao_derrubam_o_robo` | Sem as leituras do MVP, o robô registra o erro e processa todos os bairros |
| Falha | `test_chave_recusada_vira_erro_sem_vazar_a_chave` | HTTP 401 vira erro tratável; a chave não aparece em exceção nem no log |
| Falha | `test_bairro_fora_do_mvp_e_recusado` | Bairro desconhecido pelo MVP não é enviado |
| Sucesso | `test_sem_mvp_comportamento_original` | Sem `MVP_URL`, o robô funciona como antes |
| Sucesso | `test_mensagem_em_linguagem_simples` | Mensagem do site em linguagem simples, com acentos e até 400 caracteres |
| Sucesso | `test_env_preenche_sem_sobrescrever_o_ambiente` | `.env` é lido sem sobrescrever variáveis do ambiente |
| Sucesso | `test_banco_antigo_ganha_colunas_novas` | Banco criado antes da integração é migrado sozinho |

## Testes de ponta a ponta com a API real do MVP
| Evidência | Cenário |
|---|---|
| `docs/evidencias/10_integracao_mvp_real.txt` | ESP32 grava leitura no MVP, robô lê, decide, publica 4 alertas; o mapa e a lista do MVP mostram; segunda execução não duplica |
| `docs/evidencias/11_falha_mvp_fora_do_ar.txt` | MVP fora do ar (3 tentativas, erro registrado, código de saída 2), recuperação na execução seguinte e chave recusada (401) sem vazar a chave |
| `assets/mvp_alertas_do_rpa.png` | Site do MVP exibindo os alertas publicados pelo robô |
