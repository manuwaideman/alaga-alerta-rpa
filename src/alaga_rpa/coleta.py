"""Coleta de entradas: chuva prevista (Open-Meteo), boletim CGE, Ouro e leituras do robô físico."""
import csv
import json
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.error import URLError
from urllib.parse import urlencode

from .config import BAIRROS
from .db import NIVEIS
from .util import BRT, com_retry


class ErroColeta(Exception):
    """Falha ao obter uma entrada (API fora do ar, resposta inesperada...)."""


class ArquivoInvalido(Exception):
    """Arquivo existe, mas não tem o formato esperado."""


# ---------- Chuva prevista ----------
def consultar_open_meteo(lat, lon, janela_h, agora, url, timeout=10, abrir=urllib.request.urlopen):
    consulta = urlencode({"latitude": lat, "longitude": lon, "hourly": "precipitation",
                          "forecast_days": 2, "timezone": "America/Sao_Paulo"})
    try:
        with abrir(f"{url}?{consulta}", timeout=timeout) as resp:
            dados = json.load(resp)
    except (URLError, OSError, ValueError) as e:  # TimeoutError e HTTPError são OSError
        raise ErroColeta(f"Open-Meteo indisponível ({type(e).__name__})") from e
    try:
        horas = dados["hourly"]["time"]
        mm = dados["hourly"]["precipitation"]
        i = horas.index(agora.strftime("%Y-%m-%dT%H:00"))
    except (KeyError, TypeError, ValueError) as e:
        raise ErroColeta("Resposta do Open-Meteo em formato inesperado") from e
    return round(sum(v or 0 for v in mm[i:i + janela_h]), 1)


def previsao_simulada(bairro, caminho, janela_h, agora):
    """Modo simulado (documentado): lê chuva horária de um JSON de amostra."""
    try:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
        serie = dados[bairro]
    except (OSError, ValueError, KeyError) as e:
        raise ErroColeta(f"Previsão simulada ausente para {bairro}") from e
    return round(sum(serie[agora.hour:agora.hour + janela_h]), 1)


def chuva_com_cache(bairro, provedor, cfg, agora, log, dormir):
    """Tenta o provedor com retentativas; se esgotar, usa o último valor válido em cache.
    Retorna (mm, origem). Sem cache válido, levanta ErroColeta."""
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    arq = cfg.cache_dir / (bairro.replace(" ", "_") + ".json")
    try:
        mm = com_retry(provedor, cfg.tentativas, cfg.espera_base_s, dormir, (ErroColeta,), log, f"chuva {bairro}")
        arq.write_text(json.dumps({"mm": mm, "em": agora.isoformat()}), encoding="utf-8")
        return mm, cfg.origem_chuva
    except ErroColeta as erro:
        try:
            salvo = json.loads(arq.read_text(encoding="utf-8"))
            idade = agora - agora.fromisoformat(salvo["em"])
            if idade <= timedelta(hours=cfg.cache_validade_h):
                log.warning("Usando cache de chuva para %s (%.0f min de idade)", bairro, idade.total_seconds() / 60)
                return float(salvo["mm"]), "cache"
        except (OSError, ValueError, KeyError):
            pass
        raise ErroColeta(f"sem dados de chuva para {bairro}: {erro}") from erro


# ---------- Boletim CGE e Ouro (CSV) ----------
MAPA_ESTADOS = {"normal": "normal", "atencao": "atencao", "alerta": "perigo",
                "perigo": "perigo", "emergencia": "perigo"}


def _sem_acento(txt):
    return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode().strip().lower()


@dataclass
class EntradaCSV:
    estados: dict = field(default_factory=dict)  # bairro -> nivel (o mais recente)
    horas: dict = field(default_factory=dict)    # bairro -> hora da linha usada
    lidas: int = 0
    invalidas: int = 0
    duplicadas: int = 0


def ler_estados_csv(caminho, campo_hora, campo_estado):
    """Lê CSV (bairro, <hora>, <estado>), valida, descarta duplicadas e guarda o mais recente por bairro."""
    try:
        with open(caminho, encoding="utf-8", newline="") as f:
            leitor = csv.DictReader(f)
            esperado = {"bairro", campo_hora, campo_estado}
            if not leitor.fieldnames or not esperado.issubset({c.strip() for c in leitor.fieldnames}):
                raise ArquivoInvalido(f"{caminho.name}: cabeçalho deve conter {sorted(esperado)}")
            saida, vistos, recentes = EntradaCSV(), set(), {}
            for linha in leitor:
                saida.lidas += 1
                bairro = (linha.get("bairro") or "").strip()
                hora = (linha.get(campo_hora) or "").strip()
                estado = MAPA_ESTADOS.get(_sem_acento(linha.get(campo_estado) or ""))
                if bairro not in BAIRROS or not hora or estado is None:
                    saida.invalidas += 1
                    continue
                if (bairro, hora) in vistos:
                    saida.duplicadas += 1
                    continue
                vistos.add((bairro, hora))
                if bairro not in recentes or hora > recentes[bairro][0]:
                    recentes[bairro] = (hora, estado)
            saida.estados = {b: e for b, (_, e) in recentes.items()}
            saida.horas = {b: h for b, (h, _) in recentes.items()}
            return saida
    except UnicodeDecodeError as e:
        raise ArquivoInvalido(f"{caminho.name}: codificação inválida") from e


def ler_boletim(caminho):
    return ler_estados_csv(caminho, "data_hora", "estado")


def ler_ouro(caminho):
    return ler_estados_csv(caminho, "hora", "risco")


def _hora_csv(texto):
    dt = datetime.fromisoformat(texto)
    return dt if dt.tzinfo else dt.replace(tzinfo=BRT)


def filtrar_vigentes(entrada, inicio, fim):
    """Mantém só as linhas cuja hora está em [inicio, fim]. Dado velho (ou de outro dia) não decide.
    Retorna (estados_vigentes, bairros_descartados)."""
    vigentes, velhos = {}, []
    for bairro, nivel in entrada.estados.items():
        try:
            hora = _hora_csv(entrada.horas[bairro])
        except (KeyError, ValueError):
            velhos.append(bairro)
            continue
        if inicio <= hora <= fim:
            vigentes[bairro] = nivel
        else:
            velhos.append(bairro)
    return vigentes, velhos


# ---------- Leituras do robô físico (Maker Lab) ----------
def ler_leituras_sensor(conn, agora, validade_min):
    """Última leitura de cada bairro dentro da validade. Retorna {bairro: classificacao}."""
    corte = (agora - timedelta(minutes=validade_min)).isoformat(timespec="seconds")
    linhas = conn.execute(
        "SELECT bairro, classificacao, MAX(lido_em) AS t FROM leituras WHERE lido_em >= ? GROUP BY bairro", (corte,)
    ).fetchall()
    return {l["bairro"]: l["classificacao"] for l in linhas if l["classificacao"] in NIVEIS}
