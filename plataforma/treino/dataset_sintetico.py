"""Dataset histórico SINTÉTICO, usado só se o CSV real do AI4I não estiver em data/.

Reproduz o processo de geração publicado pelos autores do AI4I 2020
(Matzka, 2020), para que o projeto rode de imediato após o clone. Faz o papel
do "histórico de manutenção da fábrica". Para o relatório, use o dataset real
(instruções no README).
"""
import numpy as np
import pandas as pd

from plataforma.comum.features import MODOS_FALHA

_LIMITE_SOBRECARGA = {"L": 11000, "M": 12000, "H": 13000}


def _modos_de_falha(l: dict, rng: np.random.Generator) -> list[str]:
    modos = []
    if 200 <= l["desgaste_min"] <= 240 and rng.random() < 0.03:
        modos.append("TWF")
    if l["temp_processo_k"] - l["temp_ar_k"] < 8.6 and l["rotacao_rpm"] < 1380:
        modos.append("HDF")
    pot = l["torque_nm"] * l["rotacao_rpm"] * 2 * np.pi / 60
    if pot < 3500 or pot > 9000:
        modos.append("PWF")
    if l["desgaste_min"] * l["torque_nm"] > _LIMITE_SOBRECARGA[l["tipo"]]:
        modos.append("OSF")
    if rng.random() < 0.001:
        modos.append("RNF")
    return modos


def gerar(n: int = 10_000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    linhas = []
    for _ in range(n):
        temp_ar = rng.normal(300, 2)
        torque = max(3.0, rng.normal(40, 10))
        leitura = {
            "tipo": rng.choice(["L", "M", "H"], p=[0.5, 0.3, 0.2]),
            "temp_ar_k": temp_ar,
            "temp_processo_k": temp_ar + 10 + rng.normal(0, 1),
            "rotacao_rpm": 1538 - 15 * (torque - 40) + rng.normal(0, 80),
            "torque_nm": torque,
            "desgaste_min": float(rng.integers(0, 254)),
        }
        modos = _modos_de_falha(leitura, rng)
        leitura["falha"] = int(bool(modos))
        for m in MODOS_FALHA:
            leitura[m] = int(m in modos)
        linhas.append(leitura)
    return pd.DataFrame(linhas)
