"""Uso: python run.py [--simulado] [--agora 2026-11-17T14:00] ..."""
import argparse
import sys
import time
from datetime import datetime

from . import coleta
from .config import Config, carregar_env
from .db import conectar
from .mvp import ClienteMVP
from .notificador import Notificador
from .robo import executar
from .util import BRT, agora_brt, configurar_log, mascarar


def main(argv=None):
    p = argparse.ArgumentParser(description="Robô RPA do Alaga Alerta")
    p.add_argument("--simulado", action="store_true", help="usa previsão de chuva simulada (amostras/previsao_simulada.json)")
    p.add_argument("--agora", help="fixa a data/hora de referência, ex.: 2026-11-17T14:00 (para demo e testes)")
    p.add_argument("--db", help="caminho do banco SQLite compartilhado com a API")
    p.add_argument("--boletim", help="CSV do boletim CGE")
    p.add_argument("--ouro", help="CSV exportado da tabela Ouro")
    p.add_argument("--open-meteo-url", help="URL da API de clima (use uma inválida para demonstrar a falha)")
    p.add_argument("--mvp-url", help="URL da API central do MVP (padrão: variável MVP_URL; chave em MVP_API_KEY)")
    a = p.parse_args(argv)

    carregar_env()  # .env local (opcional); variáveis do ambiente têm prioridade
    cfg = Config()
    if a.db:
        cfg.db_path = type(cfg.db_path)(a.db)
    if a.boletim:
        cfg.boletim_csv = type(cfg.boletim_csv)(a.boletim)
    if a.ouro:
        cfg.ouro_csv = type(cfg.ouro_csv)(a.ouro)
    if a.open_meteo_url:
        cfg.open_meteo_url = a.open_meteo_url

    agora = datetime.fromisoformat(a.agora).replace(tzinfo=BRT) if a.agora else agora_brt()
    log = configurar_log(cfg.logs_dir)
    conn = conectar(cfg.db_path)

    if a.simulado:
        cfg.origem_chuva = "simulado"
        provedor = lambda b, lat, lon: coleta.previsao_simulada(b, cfg.previsao_simulada, cfg.janela_horas, agora)
        log.info("MODO SIMULADO: previsão de chuva lida de amostra local")
    else:
        provedor = lambda b, lat, lon: coleta.consultar_open_meteo(lat, lon, cfg.janela_horas, agora, cfg.open_meteo_url)

    if a.mvp_url:
        cfg.mvp_url = a.mvp_url
    mvp = None
    if cfg.mvp_url and cfg.mvp_api_key:
        mvp = ClienteMVP(cfg.mvp_url, cfg.mvp_api_key)
        log.info("Integração com o MVP ativa: %s (chave %s)", cfg.mvp_url, mascarar(cfg.mvp_api_key))
    elif cfg.mvp_url:
        log.warning("MVP_URL definida sem MVP_API_KEY: integração com o MVP desativada")

    notificador = Notificador(cfg.telegram_token, cfg.telegram_chat_id)
    try:
        res = executar(cfg, conn, provedor, notificador, agora, log, time.sleep, mvp)
    finally:
        conn.close()
    # 2 = terminou com falhas parciais (já registradas no log): o agendador percebe
    return 2 if res.falhas or res.envio_pendente or res.publicacao_pendente else 0


if __name__ == "__main__":
    sys.exit(main())
