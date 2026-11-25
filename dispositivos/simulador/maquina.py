"""Física da máquina simulada (o "mundo real" do lado do dispositivo).

Este módulo representa a máquina física: como os sensores se comportam, como
ela se degrada e quando ela de fato quebra. Ele NÃO é compartilhado com a
plataforma: a IA nunca vê estas regras, só aprende com dados históricos e
recebe a telemetria pelo MQTT, como aconteceria numa fábrica de verdade.

O comportamento segue o processo físico documentado do dataset AI4I 2020
(Matzka, 2020), para que a telemetria simulada seja realista e compatível com
os dados históricos usados no treino.
"""
import time

import numpy as np

INCREMENTO_DESGASTE = {"L": 2, "M": 3, "H": 5}            # min de desgaste por ciclo de processo
LIMITE_SOBRECARGA = {"L": 11000, "M": 12000, "H": 13000}  # desgaste x torque que quebra a ferramenta
TROCA_FERRAMENTA_ROTINA = 150                             # máquinas saudáveis trocam a ferramenta aqui
VIDA_UTIL_FERRAMENTA = 240                                # acima disso a ferramenta quebra


def potencia_w(torque_nm: float, rotacao_rpm: float) -> float:
    return torque_nm * rotacao_rpm * 2 * np.pi / 60


class MaquinaSimulada:
    def __init__(self, maquina_id: str, tipo: str, degradando: bool, rng: np.random.Generator,
                 escala_desgaste: float, deriva_torque: float, atraso_degradacao: int):
        self.id = maquina_id
        self.tipo = tipo
        self.degradando = degradando
        self.rng = rng
        self.escala_desgaste = escala_desgaste
        self.deriva_torque = deriva_torque
        self.atraso_degradacao = atraso_degradacao
        self.temp_ar = 300.0
        self.parada_restante = 0
        self._reiniciar()

    def _reiniciar(self):
        """Estado logo após uma manutenção: ferramenta nova, torque nominal."""
        self.desgaste = float(self.rng.uniform(0, 30))
        self.torque_base = 40.0
        self.leituras_desde_manutencao = 0

    def manutencao(self):
        self._reiniciar()
        self.parada_restante = 0

    def ler_sensores(self) -> dict:
        """Uma leitura dos sensores, no formato do contrato de telemetria."""
        self.leituras_desde_manutencao += 1

        # Temperatura ambiente varia lentamente (passeio aleatório)
        self.temp_ar = float(np.clip(self.temp_ar + self.rng.normal(0, 0.1), 296, 304))

        self.desgaste += INCREMENTO_DESGASTE[self.tipo] * self.escala_desgaste
        if self.degradando and self.leituras_desde_manutencao > self.atraso_degradacao:
            # Degradação: o esforço (torque) aumenta progressivamente
            self.torque_base = min(self.torque_base + self.deriva_torque, 68)
        elif self.desgaste >= TROCA_FERRAMENTA_ROTINA:
            self.desgaste = 0.0  # troca de ferramenta de rotina

        torque = max(3.0, self.rng.normal(self.torque_base, 4))
        # Rotação e torque são acoplados (potência aproximadamente constante)
        rotacao = 1538 - 15 * (torque - 40) + self.rng.normal(0, 40)
        return {
            "maquina_id": self.id,
            "ts": time.time(),
            "tipo": self.tipo,
            "temp_ar_k": round(self.temp_ar, 2),
            "temp_processo_k": round(self.temp_ar + 10 + self.rng.normal(0, 0.3), 2),
            "rotacao_rpm": round(rotacao, 1),
            "torque_nm": round(torque, 2),
            "desgaste_min": round(self.desgaste, 1),
        }

    def falhas_fisicas(self, leitura: dict) -> list[str]:
        """O que quebrou de verdade nesta leitura (o "alarme do CLP" da máquina)."""
        modos = []
        if leitura["desgaste_min"] >= VIDA_UTIL_FERRAMENTA:
            modos.append("TWF")
        if leitura["temp_processo_k"] - leitura["temp_ar_k"] < 8.6 and leitura["rotacao_rpm"] < 1380:
            modos.append("HDF")
        pot = potencia_w(leitura["torque_nm"], leitura["rotacao_rpm"])
        if pot < 3500 or pot > 9000:
            modos.append("PWF")
        if leitura["desgaste_min"] * leitura["torque_nm"] > LIMITE_SOBRECARGA[self.tipo]:
            modos.append("OSF")
        return modos
