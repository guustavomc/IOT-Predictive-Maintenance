"""Configuração central do projeto.

Tudo pode ser sobrescrito por variáveis de ambiente (é assim que o
docker-compose aponta os serviços para o broker `mosquitto`).
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# --- MQTT -----------------------------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

TOPICO_BASE = "fabrica/maquinas"
TOPICO_ALERTAS = "fabrica/alertas"


def topico(maquina_id: str, tipo: str) -> str:
    """tipo = telemetria | evento | comando"""
    return f"{TOPICO_BASE}/{maquina_id}/{tipo}"


# --- Caminhos -------------------------------------------------------------
DATASET_PATH = Path(os.getenv("DATASET_PATH", RAIZ / "data" / "ai4i2020.csv"))
MODELO_PATH = Path(os.getenv("MODELO_PATH", RAIZ / "modelos" / "modelo.joblib"))
METRICAS_PATH = Path(os.getenv("METRICAS_PATH", RAIZ / "modelos" / "metricas.json"))
DB_PATH = Path(os.getenv("DB_PATH", RAIZ / "runtime" / "telemetria.db"))

# --- Simulador (mock dos dispositivos) ------------------------------------
NUM_MAQUINAS = int(os.getenv("NUM_MAQUINAS", "5"))
MAQUINA_DEGRADANDO = os.getenv("MAQUINA_DEGRADANDO", "M-03")
INTERVALO_S = float(os.getenv("INTERVALO_S", "0.5"))          # tempo entre leituras
ESCALA_DESGASTE = float(os.getenv("ESCALA_DESGASTE", "0.5"))  # acelera/desacelera o desgaste
DERIVA_TORQUE = float(os.getenv("DERIVA_TORQUE", "0.15"))     # Nm a mais por leitura na máquina degradando
ATRASO_DEGRADACAO = int(os.getenv("ATRASO_DEGRADACAO", "30"))  # leituras normais antes de começar a degradar
LEITURAS_PARADA = int(os.getenv("LEITURAS_PARADA", "20"))      # quanto tempo a máquina fica parada após falha

# --- Inferência / alertas -------------------------------------------------
LIMIAR_ALERTA = float(os.getenv("LIMIAR_ALERTA", "0.5"))
JANELA_TENDENCIA = int(os.getenv("JANELA_TENDENCIA", "60"))      # leituras usadas para estimar a tendência
HORIZONTE_LEITURAS = int(os.getenv("HORIZONTE_LEITURAS", "50"))  # quantas leituras à frente projetar
JANELA_MEDIA = int(os.getenv("JANELA_MEDIA", "3"))  # média móvel do risco (evita alarme falso por ruído)

# --- Painel ---------------------------------------------------------------
FUSO = os.getenv("FUSO", "America/Sao_Paulo")
