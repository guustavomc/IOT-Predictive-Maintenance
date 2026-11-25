"""Mock dos dispositivos IoT (o "firmware" das máquinas simuladas).

Cada máquina simulada se comporta como um microcontrolador (ex.: ESP32) com
sensores de temperatura, rotação, torque e desgaste. A comunicação com a
plataforma segue SOMENTE o contrato em contrato/ (tópicos MQTT + JSON):

  fabrica/maquinas/<id>/telemetria   publica a leitura dos sensores
  fabrica/maquinas/<id>/evento       publica falha real / manutenção realizada
  fabrica/maquinas/<id>/comando      assina ordens vindas da plataforma

Este projeto é independente da plataforma (não importa nada dela): poderia
ser trocado por hardware real sem mudar uma linha do outro lado.

Configuração por variáveis de ambiente (ver README).
"""
import json
import os
import queue
import time

import numpy as np
import paho.mqtt.client as mqtt

from maquina import MaquinaSimulada

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPICO_BASE = "fabrica/maquinas"

NUM_MAQUINAS = int(os.getenv("NUM_MAQUINAS", "5"))
MAQUINA_DEGRADANDO = os.getenv("MAQUINA_DEGRADANDO", "M-03")
INTERVALO_S = float(os.getenv("INTERVALO_S", "0.5"))          # tempo entre leituras
ESCALA_DESGASTE = float(os.getenv("ESCALA_DESGASTE", "0.5"))  # acelera/desacelera o desgaste
DERIVA_TORQUE = float(os.getenv("DERIVA_TORQUE", "0.15"))     # Nm a mais por leitura na máquina degradando
ATRASO_DEGRADACAO = int(os.getenv("ATRASO_DEGRADACAO", "30"))  # leituras normais antes de começar a degradar
LEITURAS_PARADA = int(os.getenv("LEITURAS_PARADA", "20"))      # quanto tempo a máquina fica parada após falha


def topico(maquina_id: str, tipo: str) -> str:
    return f"{TOPICO_BASE}/{maquina_id}/{tipo}"


def conectar(client_id: str) -> mqtt.Client:
    """Conecta ao broker, tentando de novo até conseguir (como um dispositivo faria)."""
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    while True:
        try:
            cliente.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            print(f"[{client_id}] conectado ao broker {MQTT_HOST}:{MQTT_PORT}", flush=True)
            return cliente
        except OSError as erro:
            print(f"[{client_id}] broker indisponível ({erro}); tentando de novo em 2 s...", flush=True)
            time.sleep(2)


def criar_maquinas(rng) -> dict[str, MaquinaSimulada]:
    tipos = ["M", "L", "H", "L", "M"]
    maquinas = {}
    for i in range(NUM_MAQUINAS):
        mid = f"M-{i + 1:02d}"
        degradando = mid == MAQUINA_DEGRADANDO
        tipo = "L" if degradando else tipos[i % len(tipos)]
        maquinas[mid] = MaquinaSimulada(mid, tipo, degradando, rng,
                                        ESCALA_DESGASTE, DERIVA_TORQUE, ATRASO_DEGRADACAO)
    return maquinas


def main():
    rng = np.random.default_rng()
    maquinas = criar_maquinas(rng)
    cliente = conectar("simulador-maquinas")

    def publicar_evento(maquina_id, evento, detalhe):
        payload = {"maquina_id": maquina_id, "ts": time.time(), "evento": evento, "detalhe": detalhe}
        cliente.publish(topico(maquina_id, "evento"), json.dumps(payload), qos=1)

    # O callback roda na thread de rede do MQTT: ele só enfileira o comando, e o
    # laço principal o executa (uma única thread mexe nas máquinas e publica).
    comandos: queue.Queue = queue.Queue()

    def ao_receber_comando(_cliente, _userdata, msg):
        try:
            comandos.put((msg.topic.split("/")[2], json.loads(msg.payload)))
        except ValueError:
            print(f"Comando inválido ignorado em {msg.topic}", flush=True)

    def ao_conectar(cli, _userdata, _flags, _reason_code, _properties):
        cli.subscribe(f"{TOPICO_BASE}/+/comando", qos=1)

    cliente.on_connect = ao_conectar
    cliente.on_message = ao_receber_comando
    cliente.loop_start()  # rede MQTT em thread separada

    print(f"Simulando {len(maquinas)} máquinas; degradando: {MAQUINA_DEGRADANDO}", flush=True)
    while True:
        while not comandos.empty():
            maquina_id, comando = comandos.get()
            if comando.get("acao") == "manutencao" and maquina_id in maquinas:
                maquinas[maquina_id].manutencao()
                print(f"[{maquina_id}] manutenção preventiva realizada (comando da plataforma)", flush=True)
                publicar_evento(maquina_id, "manutencao", "preventiva")

        for m in maquinas.values():
            if m.parada_restante > 0:  # máquina quebrada, sem telemetria
                m.parada_restante -= 1
                if m.parada_restante == 0:
                    m.manutencao()
                    print(f"[{m.id}] manutenção corretiva concluída, máquina voltou a operar", flush=True)
                    publicar_evento(m.id, "manutencao", "corretiva")
                continue

            leitura = m.ler_sensores()
            cliente.publish(topico(m.id, "telemetria"), json.dumps(leitura))

            modos = m.falhas_fisicas(leitura)
            if modos:
                print(f"[{m.id}] FALHA REAL: {modos}. Máquina parada.", flush=True)
                publicar_evento(m.id, "falha", ",".join(modos))
                m.parada_restante = LEITURAS_PARADA
        time.sleep(INTERVALO_S)


if __name__ == "__main__":
    main()
