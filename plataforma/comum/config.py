"""Configuração central da plataforma.

Tudo pode ser sobrescrito por variáveis de ambiente (é assim que o
docker-compose aponta os serviços para o broker `mosquitto`).
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent  # raiz do repositório (/app no Docker)

# --- MQTT (tópicos definidos em contrato/README.md) -----------------------
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

TOPICO_BASE = "fabrica/maquinas"
TOPICO_ALERTAS = "fabrica/alertas"


def topico(maquina_id: str, tipo: str) -> str:
    """tipo = telemetria | evento | comando"""
    return f"{TOPICO_BASE}/{maquina_id}/{tipo}"


# --- Caminhos -------------------------------------------------------------
CONTRATO_DIR = Path(os.getenv("CONTRATO_DIR", RAIZ / "contrato"))
DATASET_PATH = Path(os.getenv("DATASET_PATH", RAIZ / "data" / "ai4i2020.csv"))
MODELO_PATH = Path(os.getenv("MODELO_PATH", RAIZ / "modelos" / "modelo.joblib"))
METRICAS_PATH = Path(os.getenv("METRICAS_PATH", RAIZ / "modelos" / "metricas.json"))
DB_PATH = Path(os.getenv("DB_PATH", RAIZ / "runtime" / "telemetria.db"))

# --- Inferência / alertas -------------------------------------------------
LIMIAR_ALERTA = float(os.getenv("LIMIAR_ALERTA", "0.5"))
JANELA_TENDENCIA = int(os.getenv("JANELA_TENDENCIA", "60"))      # leituras usadas para estimar a tendência
HORIZONTE_LEITURAS = int(os.getenv("HORIZONTE_LEITURAS", "50"))  # quantas leituras à frente projetar
JANELA_MEDIA = int(os.getenv("JANELA_MEDIA", "3"))  # média móvel do risco (evita alarme falso por ruído)

# --- Painel ---------------------------------------------------------------
FUSO = os.getenv("FUSO", "America/Sao_Paulo")
