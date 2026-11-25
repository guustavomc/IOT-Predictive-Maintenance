"""Mock dos dispositivos IoT (sensores das máquinas).

Cada máquina simulada se comporta como um microcontrolador (ex.: ESP32) com
sensores de temperatura, rotação, torque e desgaste, publicando via MQTT:

  fabrica/maquinas/<id>/telemetria   leitura dos sensores (JSON)
  fabrica/maquinas/<id>/evento       falha real / manutenção realizada
  fabrica/maquinas/<id>/comando      (assina) ordens vindas do painel, ex. manutenção

Uma máquina (MAQUINA_DEGRADANDO) se degrada ao longo do tempo: o torque sobe e
a ferramenta não é trocada, até entrar em falha por sobrecarga (OSF).
As demais trocam a ferramenta preventivamente e operam normalmente.

Para usar hardware real, basta o dispositivo publicar o mesmo JSON no mesmo
tópico: nenhum outro serviço precisa mudar.
"""
import json
import queue
import time

import numpy as np

from src import config, fisica, mqtt_util

TROCA_FERRAMENTA_ROTINA = 150  # min de desgaste em que as máquinas saudáveis trocam a ferramenta


class MaquinaSimulada:
    def __init__(self, maquina_id: str, tipo: str, degradando: bool, rng: np.random.Generator):
        self.id = maquina_id
        self.tipo = tipo
        self.degradando = degradando
        self.rng = rng
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
        self.leituras_desde_manutencao += 1

        # Temperatura ambiente varia lentamente (passeio aleatório)
        self.temp_ar = float(np.clip(self.temp_ar + self.rng.normal(0, 0.1), 296, 304))

        self.desgaste += fisica.INCREMENTO_DESGASTE[self.tipo] * config.ESCALA_DESGASTE
        if self.degradando and self.leituras_desde_manutencao > config.ATRASO_DEGRADACAO:
            # Degradação: o esforço (torque) aumenta progressivamente
            self.torque_base = min(self.torque_base + config.DERIVA_TORQUE, 68)
        elif self.desgaste >= TROCA_FERRAMENTA_ROTINA:
            self.desgaste = 0.0  # troca de ferramenta de rotina

        torque = max(3.0, self.rng.normal(self.torque_base, 4))
        return {
            "maquina_id": self.id,
            "ts": time.time(),
            "tipo": self.tipo,
            "temp_ar_k": round(self.temp_ar, 2),
            "temp_processo_k": round(self.temp_ar + 10 + self.rng.normal(0, 0.3), 2),
            "rotacao_rpm": round(fisica.rotacao_para_torque(torque, self.rng, ruido=40), 1),
            "torque_nm": round(torque, 2),
            "desgaste_min": round(self.desgaste, 1),
        }


def criar_maquinas(rng) -> dict[str, MaquinaSimulada]:
    tipos = ["M", "L", "H", "L", "M"]
    maquinas = {}
    for i in range(config.NUM_MAQUINAS):
        mid = f"M-{i + 1:02d}"
        degradando = mid == config.MAQUINA_DEGRADANDO
        tipo = "L" if degradando else tipos[i % len(tipos)]
        maquinas[mid] = MaquinaSimulada(mid, tipo, degradando, rng)
    return maquinas


def main():
    rng = np.random.default_rng()
    maquinas = criar_maquinas(rng)
    cliente = mqtt_util.conectar("simulador-maquinas")

    def publicar_evento(maquina_id, evento, detalhe):
        payload = {"maquina_id": maquina_id, "ts": time.time(), "evento": evento, "detalhe": detalhe}
        cliente.publish(config.topico(maquina_id, "evento"), json.dumps(payload), qos=1)

    # O callback roda na thread de rede do MQTT: ele só enfileira o comando, e o
    # laço principal o executa (uma única thread mexe nas máquinas e publica).
    comandos: queue.Queue = queue.Queue()

    def ao_receber_comando(_cliente, _userdata, msg):
        comandos.put((msg.topic.split("/")[2], json.loads(msg.payload)))

    def ao_conectar(cli, _userdata, _flags, _reason_code, _properties):
        cli.subscribe(f"{config.TOPICO_BASE}/+/comando", qos=1)

    cliente.on_connect = ao_conectar
    cliente.on_message = ao_receber_comando
    cliente.loop_start()  # rede MQTT em thread separada

    print(f"Simulando {len(maquinas)} máquinas; degradando: {config.MAQUINA_DEGRADANDO}")
    while True:
        while not comandos.empty():
            maquina_id, comando = comandos.get()
            if comando.get("acao") == "manutencao" and maquina_id in maquinas:
                maquinas[maquina_id].manutencao()
                print(f"[{maquina_id}] manutenção preventiva realizada (comando do painel)")
                publicar_evento(maquina_id, "manutencao", "preventiva")

        for m in maquinas.values():
            if m.parada_restante > 0:  # máquina quebrada, sem telemetria
                m.parada_restante -= 1
                if m.parada_restante == 0:
                    m.manutencao()
                    print(f"[{m.id}] manutenção corretiva concluída, máquina voltou a operar")
                    publicar_evento(m.id, "manutencao", "corretiva")
                continue

            leitura = m.ler_sensores()
            cliente.publish(config.topico(m.id, "telemetria"), json.dumps(leitura))

            modos = fisica.modos_de_falha(leitura)
            if modos:
                print(f"[{m.id}] FALHA REAL: {modos}. Máquina parada.")
                publicar_evento(m.id, "falha", ",".join(modos))
                m.parada_restante = config.LEITURAS_PARADA
        time.sleep(config.INTERVALO_S)


if __name__ == "__main__":
    main()
