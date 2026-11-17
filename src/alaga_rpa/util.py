import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRT = timezone(timedelta(hours=-3))  # horário de Brasília


def agora_brt():
    return datetime.now(BRT)


def hora_cheia(dt):
    return dt.strftime("%Y-%m-%dT%H:00")


def configurar_log(logs_dir, nome="rpa", console=True):
    """Log em arquivo diário: data/hora, nível e mensagem. Nunca registrar segredos."""
    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(nome)
    log.setLevel(logging.INFO)
    log.handlers.clear()
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
    arquivo = logging.FileHandler(Path(logs_dir) / f"rpa_{agora_brt():%Y-%m-%d}.log", encoding="utf-8")
    arquivo.setFormatter(fmt)
    log.addHandler(arquivo)
    if console:
        c = logging.StreamHandler()
        c.setFormatter(fmt)
        log.addHandler(c)
    return log


def com_retry(fn, tentativas, espera_base, dormir=time.sleep, excecoes=(Exception,), log=None, nome="operacao"):
    """Repete fn com espera exponencial. Se esgotar, relança o último erro (nunca falha em silêncio)."""
    ultimo = None
    for i in range(1, tentativas + 1):
        try:
            return fn()
        except excecoes as e:
            ultimo = e
            if log:
                log.warning("%s falhou (tentativa %d/%d): %s", nome, i, tentativas, e)
            if i < tentativas:
                dormir(espera_base * 2 ** (i - 1))
    raise ultimo


def mascarar(valor):
    v = str(valor or "")
    return "***" + v[-3:] if len(v) > 3 else "***"
