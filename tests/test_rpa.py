"""Testes do robô: SUCESSO, DECISÃO e FALHA. Rodar: python -m unittest discover -s tests -v"""
import io
import json
import logging
import sys
import tempfile
import threading
import unittest
import urllib.request
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alaga_rpa import coleta  # noqa: E402
from alaga_rpa.coleta import ArquivoInvalido, ErroColeta  # noqa: E402
from alaga_rpa.config import BAIRROS, Config  # noqa: E402
from alaga_rpa.db import conectar  # noqa: E402
from alaga_rpa.decisao import classificar_chuva, decidir  # noqa: E402
from alaga_rpa.notificador import ErroEnvio, Notificador, montar_mensagem  # noqa: E402
from alaga_rpa.robo import executar  # noqa: E402
from alaga_rpa.util import BRT, com_retry, mascarar  # noqa: E402
from datetime import datetime  # noqa: E402

AGORA = datetime(2026, 11, 17, 14, 0, tzinfo=BRT)
sem_espera = lambda s: None


class NotificadorFake(Notificador):
    def __init__(self, falhar=False):
        super().__init__("tok", "chat")
        self.falhar, self.enviadas = falhar, []

    def enviar(self, texto):
        if self.falhar:
            raise ErroEnvio("Telegram indisponível (URLError)")
        self.enviadas.append(texto)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.cfg = Config()
        self.cfg.cache_dir, self.cfg.logs_dir = t / "cache", t / "logs"
        self.cfg.boletim_csv, self.cfg.ouro_csv = t / "boletim.csv", t / "ouro.csv"
        self.cfg.espera_base_s = 0
        # Entradas válidas (só cabeçalho) por padrão; cada teste sobrescreve ou apaga o que precisar.
        self.csv(self.cfg.boletim_csv, "bairro,data_hora,estado\n")
        self.csv(self.cfg.ouro_csv, "bairro,hora,risco\n")
        self.conn = conectar(":memory:")
        self.buf = io.StringIO()
        self.log = logging.getLogger(f"teste.{id(self)}")
        self.log.setLevel(logging.INFO)
        h = logging.StreamHandler(self.buf)
        h.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
        self.log.handlers = [h]
        self.log.propagate = False

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def csv(self, caminho, texto):
        caminho.write_text(texto, encoding="utf-8")

    def chuva(self, **por_bairro):
        return lambda b, lat, lon: por_bairro.get(b.replace(" ", "_"), 0.0)

    def rodar(self, provedor, notif=None):
        return executar(self.cfg, self.conn, provedor, notif or NotificadorFake(), AGORA, self.log, sem_espera)


# ------------------------------------------------------------------ SUCESSO
class TestSucesso(Base):
    def test_chuva_forte_gera_alerta_perigo_enviado(self):
        n = NotificadorFake()
        res = self.rodar(self.chuva(Penha=35.0), n)
        linha = self.conn.execute("SELECT * FROM alertas WHERE bairro='Penha'").fetchone()
        self.assertEqual(linha["nivel"], "perigo")
        self.assertEqual(linha["status_envio"], "enviado")
        self.assertEqual((res.processados, res.alertas_novos, res.enviados, res.falhas), (6, 1, 1, 0))
        self.assertIn("PERIGO em Penha", n.enviadas[0])
        self.assertIn("199", n.enviadas[0])

    def test_leitura_csv_boletim_valida(self):
        self.csv(self.cfg.boletim_csv, "bairro,data_hora,estado\nLapa,2026-11-17T13:00,Atenção\nPenha,2026-11-17T13:00,Alerta\n")
        r = coleta.ler_boletim(self.cfg.boletim_csv)
        self.assertEqual(r.estados, {"Lapa": "atencao", "Penha": "perigo"})

    def test_open_meteo_soma_janela(self):
        horas = [f"2026-11-17T{h:02d}:00" for h in range(24)]
        mm = [0.0] * 24
        mm[14], mm[15], mm[16], mm[17] = 5.0, 6.0, 4.0, 99.0
        corpo = json.dumps({"hourly": {"time": horas, "precipitation": mm}}).encode()

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): pass
        v = coleta.consultar_open_meteo(-23.5, -46.6, 3, AGORA, "http://x", abrir=lambda url, timeout: Resp(corpo))
        self.assertEqual(v, 15.0)  # só 14h, 15h e 16h


# ------------------------------------------------------------------ DECISÃO
class TestDecisao(Base):
    def test_limiares_da_chuva(self):
        self.assertEqual(classificar_chuva(14.9, 15, 30), "normal")
        self.assertEqual(classificar_chuva(15, 15, 30), "atencao")
        self.assertEqual(classificar_chuva(29.9, 15, 30), "atencao")
        self.assertEqual(classificar_chuva(30, 15, 30), "perigo")
        self.assertEqual(classificar_chuva(None, 15, 30), "normal")

    def test_vale_o_maior_nivel_entre_as_fontes(self):
        d = decidir(5, "atencao", "normal", "perigo", self.cfg)
        self.assertEqual(d.nivel, "perigo")
        self.assertEqual(len(d.motivos), 2)

    def test_sensor_perigo_dispara_alerta_mesmo_sem_chuva(self):
        self.conn.execute("INSERT INTO leituras (sensor_id,bairro,nivel_cm,classificacao,lido_em) VALUES ('ESP32-01','Jabaquara',80,'perigo',?)",
                          (AGORA.isoformat(timespec="seconds"),))
        self.rodar(self.chuva())
        a = self.conn.execute("SELECT * FROM alertas").fetchall()
        self.assertEqual([(x["bairro"], x["nivel"]) for x in a], [("Jabaquara", "perigo")])

    def test_leitura_velha_e_ignorada(self):
        velha = (AGORA - timedelta(hours=3)).isoformat(timespec="seconds")
        self.conn.execute("INSERT INTO leituras (sensor_id,bairro,nivel_cm,classificacao,lido_em) VALUES ('ESP32-01','Jabaquara',80,'perigo',?)", (velha,))
        res = self.rodar(self.chuva())
        self.assertEqual(res.alertas_novos, 0)
        self.assertEqual(res.sem_alerta, 6)

    def test_tudo_normal_nao_alerta(self):
        res = self.rodar(self.chuva(Penha=5.0))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM alertas").fetchone()[0], 0)
        self.assertEqual(res.sem_alerta, 6)

    def test_boletim_eleva_risco(self):
        self.csv(self.cfg.boletim_csv, "bairro,data_hora,estado\nLapa,2026-11-17T13:00,Atenção\n")
        self.rodar(self.chuva())
        a = self.conn.execute("SELECT bairro, nivel FROM alertas").fetchall()
        self.assertEqual([(x[0], x[1]) for x in a], [("Lapa", "atencao")])


# ------------------------------------------------------------------ FALHA
class TestFalhas(Base):
    def test_retry_ate_funcionar(self):
        chamadas = []
        def f():
            chamadas.append(1)
            if len(chamadas) < 3:
                raise ErroColeta("fora do ar")
            return 7
        self.assertEqual(com_retry(f, 3, 0, sem_espera, (ErroColeta,)), 7)
        self.assertEqual(len(chamadas), 3)

    def test_retry_esgotado_relanca_erro(self):
        def f(): raise ErroColeta("fora do ar")
        with self.assertRaises(ErroColeta):
            com_retry(f, 3, 0, sem_espera, (ErroColeta,))

    def test_api_fora_usa_cache_valido(self):
        self.rodar(self.chuva(Penha=35.0))  # popula o cache
        def fora(b, lat, lon): raise ErroColeta("API fora do ar")
        self.conn.execute("DELETE FROM alertas")
        res = executar(self.cfg, self.conn, fora, NotificadorFake(), AGORA + timedelta(hours=1), self.log, sem_espera)
        self.assertEqual(res.falhas, 0)
        self.assertIn("Usando cache", self.buf.getvalue())
        self.assertEqual(self.conn.execute("SELECT nivel FROM alertas").fetchone()[0], "perigo")

    def test_api_fora_sem_cache_registra_falha_e_continua(self):
        def fora(b, lat, lon): raise ErroColeta("API fora do ar")
        res = self.rodar(fora)
        self.assertEqual((res.processados, res.falhas, res.sucessos), (6, 6, 0))
        self.assertIn("ERROR", self.buf.getvalue())  # nunca falha em silêncio

    def test_cache_vencido_nao_e_usado(self):
        self.rodar(self.chuva(Penha=35.0))
        def fora(b, lat, lon): raise ErroColeta("API fora do ar")
        res = executar(self.cfg, self.conn, fora, NotificadorFake(), AGORA + timedelta(hours=7), self.log, sem_espera)
        self.assertEqual(res.falhas, 6)

    def test_open_meteo_inacessivel_vira_erro_coleta(self):
        def quebra(url, timeout): raise OSError("sem rede")
        with self.assertRaises(ErroColeta):
            coleta.consultar_open_meteo(-23.5, -46.6, 3, AGORA, "http://x", abrir=quebra)

    def test_arquivo_ausente_nao_derruba_o_robo(self):
        self.cfg.boletim_csv.unlink()
        self.cfg.ouro_csv.unlink()
        res = self.rodar(self.chuva(Penha=35.0))
        self.assertIn("ausente", self.buf.getvalue())
        self.assertEqual(res.falhas, 2)          # contabilizadas, não silenciosas
        self.assertEqual(res.alertas_novos, 1)   # e o robô segue com as demais fontes

    def test_arquivo_invalido_e_registrado_como_erro(self):
        self.csv(self.cfg.boletim_csv, "regiao;situacao\nLapa;atencao\n")
        with self.assertRaises(ArquivoInvalido):
            coleta.ler_boletim(self.cfg.boletim_csv)
        res = self.rodar(self.chuva())
        self.assertEqual(res.falhas, 1)
        self.assertIn("inválido", self.buf.getvalue())

    def test_linhas_invalidas_e_duplicadas_do_csv(self):
        self.csv(self.cfg.boletim_csv,
                 "bairro,data_hora,estado\nLapa,2026-11-17T13:00,Atenção\nLapa,2026-11-17T13:00,Atenção\n"
                 "Narnia,2026-11-17T13:00,Alerta\nPenha,2026-11-17T13:00,xyz\n")
        r = coleta.ler_boletim(self.cfg.boletim_csv)
        self.assertEqual((r.lidas, r.duplicadas, r.invalidas), (4, 1, 2))
        self.assertEqual(r.estados, {"Lapa": "atencao"})

    def test_dados_duplicados_nao_duplicam_alerta(self):
        n = NotificadorFake()
        self.rodar(self.chuva(Penha=35.0), n)
        res2 = self.rodar(self.chuva(Penha=35.0), n)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM alertas").fetchone()[0], 1)
        self.assertEqual((res2.duplicados, res2.alertas_novos), (1, 0))
        self.assertEqual(len(n.enviadas), 1)  # não reenvia mensagem repetida

    def test_envio_falha_fica_pendente_e_e_reenviado(self):
        ruim = NotificadorFake(falhar=True)
        res1 = self.rodar(self.chuva(Penha=35.0), ruim)
        self.assertEqual(res1.envio_pendente, 1)
        self.assertEqual(self.conn.execute("SELECT status_envio FROM alertas").fetchone()[0], "pendente")
        self.assertIn("NÃO enviado", self.buf.getvalue())
        bom = NotificadorFake()
        res2 = self.rodar(self.chuva(), bom)
        self.assertEqual(res2.reenviados, 1)
        self.assertEqual(self.conn.execute("SELECT status_envio FROM alertas").fetchone()[0], "enviado")

    def test_log_nao_vaza_segredos(self):
        self.cfg.telegram_token, self.cfg.telegram_chat_id = "TOKEN-SECRETO-123", "987654321"
        n = NotificadorFake(); n.token = "TOKEN-SECRETO-123"
        self.rodar(self.chuva(Penha=35.0), n)
        log = self.buf.getvalue()
        self.assertNotIn("TOKEN-SECRETO-123", log)
        self.assertNotIn("987654321", log)
        self.assertEqual(mascarar("987654321"), "***321")

    def test_notificador_nao_expoe_token_no_erro(self):
        def quebra(req, timeout): raise OSError("falha")
        with self.assertRaises(ErroEnvio) as c:
            Notificador("TOKEN-SECRETO-123", "1", abrir=quebra).enviar("x")
        self.assertNotIn("TOKEN-SECRETO-123", str(c.exception))

    def test_modo_simulado_sem_credenciais(self):
        self.assertEqual(Notificador("", "").canal, "simulado")


# ------------------------------------------------------------------ INTEGRAÇÃO (API central de demonstração)
class TestIntegracaoAPI(Base):
    def test_leitura_entra_pela_api_e_alerta_sai_pela_api(self):
        from mock_api import criar_servidor
        db = Path(self.tmp.name) / "api.db"
        srv = criar_servidor(db, 0)
        porta = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{porta}"
        try:
            leitura = {"sensor_id": "ESP32-01", "bairro": "Jabaquara", "nivel_cm": 82,
                       "classificacao": "perigo", "lido_em": AGORA.isoformat(timespec="seconds")}
            req = urllib.request.Request(base + "/leituras", json.dumps(leitura).encode(), {"Content-Type": "application/json"})
            self.assertEqual(urllib.request.urlopen(req).status, 201)
            conn = conectar(db)
            executar(self.cfg, conn, self.chuva(), NotificadorFake(), AGORA, self.log, sem_espera)
            conn.close()
            alertas = json.load(urllib.request.urlopen(base + "/alertas"))
            self.assertEqual([(a["bairro"], a["nivel"]) for a in alertas], [("Jabaquara", "perigo")])
            ruim = urllib.request.Request(base + "/leituras", b'{"x":1}', {"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(ruim)
            self.assertEqual(e.exception.code, 400)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
