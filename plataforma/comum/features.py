"""Engenharia de atributos (features) do modelo de IA.

Usado igualmente no treino e na inferência, para que o modelo veja os dados
sempre no mesmo formato. A plataforma não conhece as regras físicas de falha
das máquinas: ela só transforma as leituras em atributos e deixa a IA aprender
os padrões com os dados históricos.
"""
import numpy as np
import pandas as pd

TIPO_COD = {"L": 0, "M": 1, "H": 2}  # qualidade do produto: Low / Medium / High

# Rótulos de falha do dataset histórico (AI4I 2020)
MODOS_FALHA = ["TWF", "HDF", "PWF", "OSF", "RNF"]
NOMES_FALHA = {
    "TWF": "Desgaste da ferramenta",
    "HDF": "Dissipação de calor",
    "PWF": "Potência fora da faixa",
    "OSF": "Sobrecarga (desgaste x torque)",
    "RNF": "Falha aleatória",
}

# Colunas do CSV original -> nomes usados no projeto (e no contrato de telemetria)
COLUNAS_AI4I = {
    "Type": "tipo",
    "Air temperature [K]": "temp_ar_k",
    "Process temperature [K]": "temp_processo_k",
    "Rotational speed [rpm]": "rotacao_rpm",
    "Torque [Nm]": "torque_nm",
    "Tool wear [min]": "desgaste_min",
    "Machine failure": "falha",
}

SENSORES = ["temp_ar_k", "temp_processo_k", "rotacao_rpm", "torque_nm", "desgaste_min"]

FEATURES = [
    "tipo_cod",
    *SENSORES,
    # features derivadas: grandezas físicas que costumam explicar falhas mecânicas
    "delta_temp_k",       # dissipação de calor
    "potencia_w",         # potência mecânica = torque x velocidade angular
    "desgaste_x_torque",  # esforço acumulado sobre a ferramenta
]


def montar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Recebe leituras brutas (sensores + tipo) e devolve a matriz de features do modelo."""
    df = df.copy()
    df["tipo_cod"] = df["tipo"].map(TIPO_COD)
    df["delta_temp_k"] = df["temp_processo_k"] - df["temp_ar_k"]
    df["potencia_w"] = df["torque_nm"] * df["rotacao_rpm"] * 2 * np.pi / 60
    df["desgaste_x_torque"] = df["desgaste_min"] * df["torque_nm"]
    return df[FEATURES]
