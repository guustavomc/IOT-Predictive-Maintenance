"""Camada de armazenamento da telemetria (SQLite).

Isolada neste módulo para facilitar a troca por um banco de séries temporais
(InfluxDB / TimescaleDB) sem mexer nos outros serviços.
"""
import sqlite3

from plataforma.comum import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS leituras (
    ts REAL, maquina_id TEXT, tipo TEXT,
    temp_ar_k REAL, temp_processo_k REAL, rotacao_rpm REAL, torque_nm REAL, desgaste_min REAL,
    prob_atual REAL, risco REAL
);
CREATE INDEX IF NOT EXISTS idx_leituras_ts ON leituras (ts);
CREATE TABLE IF NOT EXISTS alertas (
    ts REAL, maquina_id TEXT, risco REAL, tipo_falha TEXT, mensagem TEXT
);
CREATE TABLE IF NOT EXISTS eventos (
    ts REAL, maquina_id TEXT, evento TEXT, detalhe TEXT
);
"""


def conectar(path=config.DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")  # permite o painel ler enquanto a inferência escreve
    con.executescript(SCHEMA)
    return con


def salvar_leituras(con, linhas: list[tuple[dict, float, float]]):
    """Grava um lote de (leitura, prob_atual, risco) numa única transação."""
    con.executemany(
        "INSERT INTO leituras VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(l["ts"], l["maquina_id"], l["tipo"], l["temp_ar_k"], l["temp_processo_k"],
          l["rotacao_rpm"], l["torque_nm"], l["desgaste_min"], prob_atual, risco)
         for l, prob_atual, risco in linhas],
    )
    con.commit()


def salvar_alerta(con, alerta: dict):
    con.execute(
        "INSERT INTO alertas VALUES (?,?,?,?,?)",
        (alerta["ts"], alerta["maquina_id"], alerta["risco"], alerta["tipo_falha"], alerta["mensagem"]),
    )
    con.commit()


def salvar_evento(con, evento: dict):
    con.execute(
        "INSERT INTO eventos VALUES (?,?,?,?)",
        (evento["ts"], evento["maquina_id"], evento["evento"], evento.get("detalhe", "")),
    )
    con.commit()
