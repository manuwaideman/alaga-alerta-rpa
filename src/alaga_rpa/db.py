"""Banco compartilhado (SQLite). A API central do MVP lê a tabela `alertas`."""
import sqlite3
from pathlib import Path

NIVEIS = ("normal", "atencao", "perigo")

SCHEMA = """
CREATE TABLE IF NOT EXISTS alertas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    bairro        TEXT NOT NULL,
    nivel         TEXT NOT NULL CHECK (nivel IN ('atencao','perigo')),
    motivo        TEXT NOT NULL,
    chuva_mm      REAL,
    hora_ref      TEXT NOT NULL,
    criado_em     TEXT NOT NULL,
    canal         TEXT,
    status_envio  TEXT NOT NULL DEFAULT 'pendente' CHECK (status_envio IN ('pendente','enviado')),
    tentativas    INTEGER NOT NULL DEFAULT 0,
    publicado_mvp INTEGER NOT NULL DEFAULT 0,  -- 1 = já está na API central do MVP
    id_mvp        INTEGER,
    UNIQUE (bairro, nivel, hora_ref)
);
CREATE TABLE IF NOT EXISTS leituras (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id     TEXT NOT NULL,
    bairro        TEXT NOT NULL,
    nivel_cm      REAL,
    classificacao TEXT NOT NULL CHECK (classificacao IN ('normal','atencao','perigo')),
    lido_em       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execucoes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio        TEXT NOT NULL,
    fim           TEXT NOT NULL,
    processados   INTEGER, sucessos INTEGER, falhas INTEGER,
    alertas_novos INTEGER, duplicados INTEGER, enviados INTEGER, pendentes INTEGER
);
"""


def conectar(db_path):
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrar(conn)
    return conn


def _migrar(conn):
    """Bancos criados antes da integração com o MVP ganham as colunas novas."""
    colunas = {c["name"] for c in conn.execute("PRAGMA table_info(alertas)")}
    if "publicado_mvp" not in colunas:
        conn.execute("ALTER TABLE alertas ADD COLUMN publicado_mvp INTEGER NOT NULL DEFAULT 0")
    if "id_mvp" not in colunas:
        conn.execute("ALTER TABLE alertas ADD COLUMN id_mvp INTEGER")
    conn.commit()
