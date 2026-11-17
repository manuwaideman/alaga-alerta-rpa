"""Testes da integração com a API central do MVP e da validade dos dados.
Rodar junto com os demais: python -m unittest discover -s tests -v"""
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from alaga_rpa.db import conectar  # noqa: E402
from alaga_rpa.mvp import ClienteMVP, ErroMVP, mensagem_mvp  # noqa: E402
from alaga_rpa.robo import executar  # noqa: E402
from test_rpa import AGORA, Base, NotificadorFake, sem_espera  # noqa: E402

CHAVE = "chave-secreta-do-mvp-123"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class MVPFalso:
    """Imita a API central: guarda os POST /alertas e devolve leituras configuradas."""

    def __init__(self, leituras=None, fora_do_ar=False, http=None):
        self.leituras, self.fora_do_ar, self.http = leituras or [], fora_do_ar, http
        self.alertas, self.chaves = [], []

    def __call__(self, req, timeout=10):
        self.chaves.append(req.get_header("X-api-key"))
        if self.fora_do_ar:
            raise URLError("connection refused")
        if self.http:
            raise HTTPError(req.full_url, self.http, "erro", {}, None)
        if req.get_method() == "GET" and "/leituras" in req.full_url:
            return _Resp(json.dumps(self.leituras).encode())
        if req.get_method() == "POST" and req.full_url.endswith("/alertas"):
            corpo = json.loads(req.data)
            self.alertas.append(corpo)
            return _Resp(json.dumps({"id": len(self.alertas)}).encode())
        raise AssertionError(f"rota inesperada {req.get_method()} {req.full_url}")


class TestIntegracaoMVP(Base):
    def rodar_mvp(self, provedor, falso, notif=None):
        mvp = ClienteMVP("http://mvp.teste", CHAVE, abrir=falso)
        return executar(self.cfg, self.conn, provedor, notif or NotificadorFake(), AGORA, self.log, sem_espera, mvp)

    def test_alerta_e_publicado_no_contrato_do_mvp(self):
        falso = MVPFalso()
        res = self.rodar_mvp(self.chuva(Penha=35.0, Lapa=20.0), falso)
        self.assertEqual(res.publicados_mvp, 2)
        por_bairro = {a["bairro_id"]: a for a in falso.alertas}
        self.assertEqual(por_bairro["penha"]["nivel"], "alto")        # perigo -> alto
        self.assertEqual(por_bairro["lapa"]["nivel"], "atencao")
        self.assertEqual(por_bairro["penha"]["origem"], "rpa")
        self.assertIn("199", por_bairro["penha"]["mensagem"])
        self.assertLessEqual(len(por_bairro["penha"]["mensagem"]), 400)
        self.assertTrue(all(c == CHAVE for c in falso.chaves))
        linha = self.conn.execute("SELECT publicado_mvp, id_mvp FROM alertas WHERE bairro='Penha'").fetchone()
        self.assertEqual((linha["publicado_mvp"], linha["id_mvp"]), (1, 1) if falso.alertas[0]["bairro_id"] == "penha" else (1, 2))

    def test_mvp_fora_do_ar_fica_pendente_e_e_republicado(self):
        fora = MVPFalso(fora_do_ar=True)
        res = self.rodar_mvp(self.chuva(Penha=35.0), fora)
        self.assertEqual(res.publicacao_pendente, 1)
        self.assertEqual(self.conn.execute("SELECT publicado_mvp FROM alertas").fetchone()[0], 0)
        self.assertIn("NÃO publicado no MVP", self.buf.getvalue())

        volta = MVPFalso()
        res2 = self.rodar_mvp(self.chuva(Penha=35.0), volta)
        self.assertEqual(res2.duplicados, 1)          # não cria alerta novo...
        self.assertEqual(res2.publicados_mvp, 1)       # ...mas publica o que faltava
        self.assertEqual(len(volta.alertas), 1)
        self.assertEqual(self.conn.execute("SELECT publicado_mvp FROM alertas").fetchone()[0], 1)

    def test_leitura_de_perigo_vinda_do_mvp_dispara_alerta(self):
        falso = MVPFalso(leituras=[
            {"sensor_id": "esp32-01", "bairro_id": "jabaquara", "nivel_cm": 80, "classificacao": "perigo",
             "medido_em": "2026-11-17T16:50:00+00:00"},        # 13:50 em Brasília: dentro de 60 min
            {"sensor_id": "esp32-02", "bairro_id": "lapa", "nivel_cm": 80, "classificacao": "perigo",
             "medido_em": "2026-11-16T16:50:00+00:00"},        # ontem: ignorada
            {"sensor_id": "esp32-03", "bairro_id": "vila-formosa", "nivel_cm": 80, "classificacao": "perigo",
             "medido_em": "2026-11-17T16:55:00+00:00"},        # bairro que o RPA não monitora: ignorada
        ])
        res = self.rodar_mvp(self.chuva(), falso)
        self.assertEqual(res.alertas_novos, 1)
        self.assertEqual(falso.alertas[0]["bairro_id"], "jabaquara")
        self.assertIn("sensor", falso.alertas[0]["mensagem"])

    def test_leituras_do_mvp_indisponiveis_nao_derrubam_o_robo(self):
        res = self.rodar_mvp(self.chuva(Penha=35.0), MVPFalso(fora_do_ar=True))
        self.assertEqual(res.processados, 6)
        self.assertGreaterEqual(res.falhas, 1)
        self.assertIn("Leituras do MVP indisponíveis", self.buf.getvalue())

    def test_chave_recusada_vira_erro_sem_vazar_a_chave(self):
        cli = ClienteMVP("http://mvp.teste", CHAVE, abrir=MVPFalso(http=401))
        with self.assertRaises(ErroMVP) as ctx:
            cli.publicar_alerta("Penha", "perigo", ["teste"], 3, "simulado")
        self.assertIn("401", str(ctx.exception))
        self.assertNotIn(CHAVE, str(ctx.exception))
        self.rodar_mvp(self.chuva(Penha=35.0), MVPFalso(http=401))
        self.assertNotIn(CHAVE, self.buf.getvalue())

    def test_bairro_fora_do_mvp_e_recusado(self):
        with self.assertRaises(ErroMVP):
            ClienteMVP("http://x", CHAVE, abrir=MVPFalso()).publicar_alerta("Narnia", "perigo", ["x"], 3, "simulado")

    def test_sem_mvp_comportamento_original(self):
        res = self.rodar(self.chuva(Penha=35.0))
        self.assertEqual((res.publicados_mvp, res.publicacao_pendente), (0, 0))

    def test_mensagem_em_linguagem_simples(self):
        self.assertTrue(mensagem_mvp("Penha", "perigo", ["chuva 36 mm"]).startswith("Risco alto de alagamento em Penha"))
        self.assertTrue(mensagem_mvp("Lapa", "atencao", ["boletim"]).startswith("Atenção de alagamento em Lapa"))
        self.assertIn("boletim CGE: atenção", mensagem_mvp("Lapa", "atencao", ["boletim CGE: atencao"]))


class TestValidadeDosDados(Base):
    def test_boletim_de_ontem_nao_gera_alerta(self):
        self.csv(self.cfg.boletim_csv, "bairro,data_hora,estado\nPenha,2026-11-16T13:00,Alerta\n")
        res = self.rodar(self.chuva())
        self.assertEqual(res.alertas_novos, 0)
        self.assertIn("fora da validade", self.buf.getvalue())

    def test_boletim_recente_continua_valendo(self):
        self.csv(self.cfg.boletim_csv, "bairro,data_hora,estado\nPenha,2026-11-17T12:00,Alerta\n")
        self.assertEqual(self.rodar(self.chuva()).alertas_novos, 1)

    def test_ouro_de_outro_horario_e_ignorada(self):
        self.csv(self.cfg.ouro_csv, "bairro,hora,risco\nLapa,2026-11-17T08:00,perigo\nPenha,2026-11-17T15:00,atencao\n")
        res = self.rodar(self.chuva())
        bairros = {r["bairro"] for r in self.conn.execute("SELECT bairro FROM alertas")}
        self.assertEqual(bairros, {"Penha"})
        self.assertEqual(res.alertas_novos, 1)


class TestArquivoEnv(unittest.TestCase):
    def test_env_preenche_sem_sobrescrever_o_ambiente(self):
        import os
        from alaga_rpa.config import carregar_env
        with tempfile.TemporaryDirectory() as t:
            arq = Path(t) / ".env"
            arq.write_text("# comentario\nALAGA_TESTE_A=do_arquivo\nALAGA_TESTE_B=do_arquivo\nALAGA_TESTE_VAZIA=\n", encoding="utf-8")
            os.environ["ALAGA_TESTE_B"] = "do_ambiente"
            try:
                carregar_env(arq)
                self.assertEqual(os.environ["ALAGA_TESTE_A"], "do_arquivo")
                self.assertEqual(os.environ["ALAGA_TESTE_B"], "do_ambiente")
                self.assertNotIn("ALAGA_TESTE_VAZIA", os.environ)
            finally:
                for k in ("ALAGA_TESTE_A", "ALAGA_TESTE_B"):
                    os.environ.pop(k, None)


class TestMigracao(unittest.TestCase):
    def test_banco_antigo_ganha_colunas_novas(self):
        with tempfile.TemporaryDirectory() as t:
            caminho = Path(t) / "antigo.db"
            antigo = sqlite3.connect(caminho)
            antigo.execute("CREATE TABLE alertas (id INTEGER PRIMARY KEY, bairro TEXT NOT NULL, nivel TEXT NOT NULL, "
                           "motivo TEXT NOT NULL, chuva_mm REAL, hora_ref TEXT NOT NULL, criado_em TEXT NOT NULL, "
                           "canal TEXT, status_envio TEXT NOT NULL DEFAULT 'pendente', tentativas INTEGER NOT NULL DEFAULT 0, "
                           "UNIQUE (bairro, nivel, hora_ref))")
            antigo.commit()
            antigo.close()
            conn = conectar(caminho)
            colunas = {c["name"] for c in conn.execute("PRAGMA table_info(alertas)")}
            conn.close()
            self.assertTrue({"publicado_mvp", "id_mvp"} <= colunas)


if __name__ == "__main__":
    unittest.main()
