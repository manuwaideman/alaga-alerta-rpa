"""API central MÍNIMA para demonstrar a integração (o MVP real tem a sua).
Contrato:  GET /health | GET /alertas | GET /leituras | POST /leituras
Lê/grava o mesmo banco SQLite que o robô."""
import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from alaga_rpa.db import NIVEIS, conectar


def criar_servidor(db_path, porta=8000):
    class H(BaseHTTPRequestHandler):
        def _json(self, codigo, obj):
            corpo = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            rota = urlparse(self.path).path
            if rota == "/health":
                return self._json(200, {"status": "ok"})
            if rota in ("/alertas", "/leituras"):
                conn = conectar(db_path)
                linhas = conn.execute(f"SELECT * FROM {rota[1:]} ORDER BY id DESC LIMIT 100").fetchall()
                conn.close()
                return self._json(200, [dict(l) for l in linhas])
            self._json(404, {"erro": "rota não encontrada"})

        def do_POST(self):
            if urlparse(self.path).path != "/leituras":
                return self._json(404, {"erro": "rota não encontrada"})
            try:
                n = int(self.headers.get("Content-Length", 0))
                d = json.loads(self.rfile.read(n))
                assert d["classificacao"] in NIVEIS and d["sensor_id"] and d["bairro"] and d["lido_em"]
            except (ValueError, KeyError, AssertionError, TypeError):
                return self._json(400, {"erro": "JSON inválido: use sensor_id, bairro, nivel_cm, classificacao, lido_em"})
            conn = conectar(db_path)
            conn.execute("INSERT INTO leituras (sensor_id, bairro, nivel_cm, classificacao, lido_em) VALUES (?,?,?,?,?)",
                         (d["sensor_id"], d["bairro"], d.get("nivel_cm"), d["classificacao"], d["lido_em"]))
            conn.commit()
            conn.close()
            self._json(201, {"status": "gravado"})

        def log_message(self, *a):
            pass

    return HTTPServer(("127.0.0.1", porta), H)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "data" / "alaga.db"))
    ap.add_argument("--porta", type=int, default=8000)
    a = ap.parse_args()
    print(f"API de demonstração em http://127.0.0.1:{a.porta}")
    criar_servidor(a.db, a.porta).serve_forever()
