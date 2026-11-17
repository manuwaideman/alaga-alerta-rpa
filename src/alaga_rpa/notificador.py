"""Canal de alerta. Telegram quando configurado; senão modo simulado (só log)."""
import json
import urllib.request
from urllib.error import URLError
from urllib.parse import urlencode

ORIENTACAO = {
    "atencao": "Acompanhe a previsão e evite ruas baixas e margens de córregos.",
    "perigo": "Evite sair e não atravesse ruas alagadas. Emergência: Defesa Civil, 199.",
}


class ErroEnvio(Exception):
    pass


def montar_mensagem(bairro, nivel, motivos, hora_ref):
    return (f"Alaga Alerta | {nivel.upper()} em {bairro}\n"
            f"Motivo: {'; '.join(motivos)}\n"
            f"O que fazer: {ORIENTACAO[nivel]}\n"
            f"Referência: {hora_ref}")


class Notificador:
    def __init__(self, token="", chat_id="", abrir=urllib.request.urlopen, timeout=10):
        self.token, self.chat_id, self.abrir, self.timeout = token, chat_id, abrir, timeout

    @property
    def canal(self):
        return "telegram" if self.token and self.chat_id else "simulado"

    def enviar(self, texto):
        if self.canal == "simulado":
            return
        corpo = urlencode({"chat_id": self.chat_id, "text": texto}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/sendMessage", data=corpo)
        try:
            with self.abrir(req, timeout=self.timeout) as resp:
                ok = json.load(resp).get("ok")
        except (URLError, OSError, ValueError) as e:
            # Não repassa a mensagem original: a URL contém o token.
            raise ErroEnvio(f"Telegram indisponível ({type(e).__name__})") from None
        if not ok:
            raise ErroEnvio("Telegram recusou a mensagem")
