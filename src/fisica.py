"""Modelo físico simplificado das máquinas.

Reproduz as regras do dataset AI4I 2020 (Matzka, 2020 - UCI ML Repository),
para que os dados simulados tenham a MESMA distribuição dos dados de treino.
Isso é importante: se o simulador gerar valores fora do que o modelo viu,
as previsões perdem o sentido.

Modos de falha do AI4I:
  TWF  desgaste da ferramenta (fim de vida, 200-240 min)
  HDF  dissipação de calor (Δtemperatura < 8,6 K e rotação < 1380 rpm)
  PWF  potência fora da faixa (< 3500 W ou > 9000 W)
  OSF  sobrecarga (desgaste x torque acima do limite do tipo de produto)
  RNF  falha aleatória (0,1%)
"""
import numpy as np
import pandas as pd

TIPOS = ("L", "M", "H")  # qualidade do produto: Low / Medium / High
TIPO_COD = {"L": 0, "M": 1, "H": 2}
INCREMENTO_DESGASTE = {"L": 2, "M": 3, "H": 5}  # min de desgaste por processo
LIMITE_SOBRECARGA = {"L": 11000, "M": 12000, "H": 13000}  # min·Nm

MODOS_FALHA = ["TWF", "HDF", "PWF", "OSF", "RNF"]
NOMES_FALHA = {
    "TWF": "Desgaste da ferramenta",
    "HDF": "Dissipação de calor",
    "PWF": "Potência fora da faixa",
    "OSF": "Sobrecarga (desgaste x torque)",
    "RNF": "Falha aleatória",
}

# Colunas do CSV original -> nomes usados no projeto (e no JSON do MQTT)
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
    # features derivadas ("engenharia de atributos"): grandezas físicas que explicam as falhas
    "delta_temp_k",
    "potencia_w",
    "desgaste_x_torque",
]


def potencia_w(torque_nm, rotacao_rpm):
    return torque_nm * rotacao_rpm * 2 * np.pi / 60


def montar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Recebe leituras brutas (sensores + tipo) e devolve a matriz de features do modelo."""
    df = df.copy()
    df["tipo_cod"] = df["tipo"].map(TIPO_COD)
    df["delta_temp_k"] = df["temp_processo_k"] - df["temp_ar_k"]
    df["potencia_w"] = potencia_w(df["torque_nm"], df["rotacao_rpm"])
    df["desgaste_x_torque"] = df["desgaste_min"] * df["torque_nm"]
    return df[FEATURES]


def modos_de_falha(leitura: dict, rng: np.random.Generator | None = None) -> list[str]:
    """Aplica as regras físicas a uma leitura e retorna os modos de falha ativos.

    Com `rng` (geração do dataset) inclui as falhas estocásticas (TWF e RNF).
    Sem `rng` (simulador) usa só as regras determinísticas.
    """
    modos = []
    desgaste = leitura["desgaste_min"]
    torque = leitura["torque_nm"]
    rpm = leitura["rotacao_rpm"]

    if rng is not None:
        if 200 <= desgaste <= 240 and rng.random() < 0.03:  # no AI4I a troca ocorre ao acaso nessa faixa
            modos.append("TWF")
    elif desgaste >= 240:  # no simulador: ferramenta chegou ao fim de vida
        modos.append("TWF")
    if leitura["temp_processo_k"] - leitura["temp_ar_k"] < 8.6 and rpm < 1380:
        modos.append("HDF")
    pot = potencia_w(torque, rpm)
    if pot < 3500 or pot > 9000:
        modos.append("PWF")
    if desgaste * torque > LIMITE_SOBRECARGA[leitura["tipo"]]:
        modos.append("OSF")
    if rng is not None and rng.random() < 0.001:
        modos.append("RNF")
    return modos


def rotacao_para_torque(torque_nm: float, rng: np.random.Generator, ruido: float) -> float:
    """No AI4I rotação e torque são fortemente correlacionados (corr ≈ -0,88)."""
    return 1538 - 15 * (torque_nm - 40) + rng.normal(0, ruido)


def gerar_dataset_sintetico(n: int = 10_000, seed: int = 42) -> pd.DataFrame:
    """Gera um dataset no formato do AI4I. Usado só se o CSV real não estiver em data/.

    Para o relatório final, usem o dataset REAL (veja o README).
    """
    rng = np.random.default_rng(seed)
    linhas = []
    for _ in range(n):
        tipo = rng.choice(TIPOS, p=[0.5, 0.3, 0.2])
        temp_ar = rng.normal(300, 2)
        torque = max(3.0, rng.normal(40, 10))
        leitura = {
            "tipo": tipo,
            "temp_ar_k": temp_ar,
            "temp_processo_k": temp_ar + 10 + rng.normal(0, 1),
            "rotacao_rpm": rotacao_para_torque(torque, rng, ruido=80),
            "torque_nm": torque,
            "desgaste_min": float(rng.integers(0, 254)),
        }
        modos = modos_de_falha(leitura, rng)
        leitura["falha"] = int(bool(modos))
        for m in MODOS_FALHA:
            leitura[m] = int(m in modos)
        linhas.append(leitura)
    return pd.DataFrame(linhas)
