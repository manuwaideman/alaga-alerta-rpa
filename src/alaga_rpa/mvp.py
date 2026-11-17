"""Integração com a API central do MVP Alaga Alerta.

Ativada quando MVP_URL e MVP_API_KEY estão no ambiente. Duas direções:
  - ENTRADA: leituras do robô físico que o ESP32 já enviou para o MVP
    (GET /leituras), para o RPA usar o sensor mesmo sem a API de demonstração.
  - SAÍDA: cada alerta gravado pelo robô é publicado no MVP (POST /alertas),
    que o mostra ao cidadão no site. Se o MVP estiver fora do ar, o alerta
    fica marcado como não publicado e é republicado na próxima execução.

Contrato do MVP: docs/CONTRATOS.md do repositório da API central.
Só biblioteca padrão, como o resto do robô.
"""
import json
import urllib.request
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError

from .config import BAIRRO_ID
from .util import BRT

# Vocabulário do RPA -> vocabulário do MVP
NIVEL_MVP = {"atencao": "atencao", "perigo": "alto"}
ORIENTACAO_CURTA = {
    "atencao": "Evite ruas que costumam alagar e acompanhe os avisos.",
    "perigo": "Evite sair e nunca atravesse rua alagada. Emergência: Defesa Civil 199.",
}
ID_PARA_BAIRRO = {v: k for k, v in BAIRRO_ID.items()}


class ErroMVP(Exception):
    """Falha ao falar com a API central (fora do ar, chave recusada, resposta inválida)."""


def _parse(valor):
    dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=BRT)


ROTULOS = {": atencao": ": atenção", ": perigo": ": perigo", ": normal": ": normal"}


def mensagem_mvp(bairro, nivel, motivos):
    """Texto curto (até 400 caracteres, limite do MVP) em linguagem simples, com acentos."""
    rotulo = "Risco alto" if nivel == "perigo" else "Atenção"
    motivo = "; ".join(motivos)
    for de, para in ROTULOS.items():
        motivo = motivo.replace(de, para)
    texto = f"{rotulo} de alagamento em {bairro}. Motivo: {motivo}. {ORIENTACAO_CURTA[nivel]}"
    return texto[:400]


class ClienteMVP:
    def __init__(self, url, chave, abrir=urllib.request.urlopen, timeout=10):
        self.url, self.chave, self.abrir, self.timeout = url.rstrip("/"), chave, abrir, timeout

    def _req(self, metodo, rota, corpo=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.url + rota, data=dados, method=metodo)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-API-Key", self.chave)
        try:
            with self.abrir(req, timeout=self.timeout) as resp:
                return json.load(resp)
        except HTTPError as e:
            # Nunca repassa cabeçalhos nem corpo: só o código HTTP.
            raise ErroMVP(f"MVP respondeu HTTP {e.code} em {rota}") from None
        except (URLError, OSError, ValueError) as e:
            raise ErroMVP(f"MVP indisponível em {rota} ({type(e).__name__})") from None

    def leituras(self, agora, validade_min):
        """Última leitura válida de cada bairro monitorado: {nome_do_bairro: classificacao}."""
        corte = agora - timedelta(minutes=validade_min)
        resultado, momentos = {}, {}
        for l in self._req("GET", "/leituras?limite=200"):
            bairro = ID_PARA_BAIRRO.get(l.get("bairro_id"))
            if not bairro or l.get("classificacao") not in ("normal", "atencao", "perigo"):
                continue
            medido = _parse(l["medido_em"])
            # Janela relativa ao horário de referência; aceita leituras até 5 min "no futuro"
            # (relógio do ESP32 adiantado), mas não leituras de outro dia.
            if not (corte <= medido <= agora + timedelta(minutes=5)):
                continue
            if bairro not in momentos or medido > momentos[bairro]:
                momentos[bairro], resultado[bairro] = medido, l["classificacao"]
        return resultado

    def publicar_alerta(self, bairro, nivel, motivos, janela_h, canal, emitido_em=None):
        """POST /alertas. Retorna o id do alerta no MVP."""
        if bairro not in BAIRRO_ID:
            raise ErroMVP(f"bairro '{bairro}' não existe no MVP")
        emitido = emitido_em or datetime.now(BRT)
        corpo = {
            "bairro_id": BAIRRO_ID[bairro],
            "nivel": NIVEL_MVP[nivel],
            "mensagem": mensagem_mvp(bairro, nivel, motivos),
            "criado_em": emitido.isoformat(timespec="seconds"),
            "valido_ate": (emitido + timedelta(hours=janela_h)).isoformat(timespec="seconds"),
            "origem": "rpa",
            "canais": canal,
        }
        return self._req("POST", "/alertas", corpo)["id"]
