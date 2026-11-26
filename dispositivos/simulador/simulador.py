"""Mock de UM dispositivo IoT (o "firmware" de uma máquina simulada).

Cada processo/container é uma máquina, como um microcontrolador (ex.: ESP32)
instalado num equipamento, com sua própria identidade e sua própria conexão
MQTT. A comunicação com a plataforma segue SOMENTE o contrato em contrato/:

  fabrica/maquinas/<id>/telemetria   publica a leitura dos sensores
  fabrica/maquinas/<id>/evento       publica falha real / manutenção realizada
  fabrica/maquinas/<id>/status       online/offline (retido; offline via Last Will)
  fabrica/maquinas/<id>/comando      assina as ordens enviadas para ESTA máquina

Este projeto é independente da plataforma (não importa nada dela): poderia
ser trocado por hardware real sem mudar uma linha do outro lado.

Configuração por variáveis de ambiente (ver README).
"""
import json
import os
import queue
import re
import signal
import time

import numpy as np
import paho.mqtt.client as mqtt

from maquina import MaquinaSimulada

# --- Identidade do dispositivo ---------------------------------------------
MAQUINA_ID = os.getenv("MAQUINA_ID", "M-01")
TIPO_PRODUTO = os.getenv("TIPO_PRODUTO", "L")                           # L / M / H
DEGRADANDO = os.getenv("DEGRADANDO", "false").lower() in ("1", "true", "sim", "yes")

# --- Conexão --------------------------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPICO_BASE = "fabrica/maquinas"

# --- Comportamento da simulação -------------------------------------------
INTERVALO_S = float(os.getenv("INTERVALO_S", "0.5"))          # tempo entre leituras
ESCALA_DESGASTE = float(os.getenv("ESCALA_DESGASTE", "0.5"))  # acelera/desacelera o desgaste
DERIVA_TORQUE = float(os.getenv("DERIVA_TORQUE", "0.15"))     # Nm a mais por leitura quando degradando
ATRASO_DEGRADACAO = int(os.getenv("ATRASO_DEGRADACAO", "30"))  # leituras normais antes de começar a degradar
LEITURAS_PARADA = int(os.getenv("LEITURAS_PARADA", "20"))      # quanto tempo a máquina fica parada após falha


def log(msg: str):
    print(f"[{MAQUINA_ID}] {msg}", flush=True)


def topico(tipo: str) -> str:
    return f"{TOPICO_BASE}/{MAQUINA_ID}/{tipo}"


def validar_configuracao():
    if not re.fullmatch(r"[A-Za-z0-9_-]+", MAQUINA_ID):
        raise SystemExit(f"MAQUINA_ID inválido: {MAQUINA_ID!r} (use letras, números, '-' ou '_')")
    if TIPO_PRODUTO not in ("L", "M", "H"):
        raise SystemExit(f"TIPO_PRODUTO inválido: {TIPO_PRODUTO!r} (use L, M ou H)")


def payload_status(status: str, motivo: str = "") -> str:
    return json.dumps({"maquina_id": MAQUINA_ID, "ts": time.time(), "status": status, "motivo": motivo})


def conectar() -> mqtt.Client:
    """Conecta ao broker, tentando de novo até conseguir (como um dispositivo faria)."""
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"maquina-{MAQUINA_ID}")
    # Last Will ("testamento"): se a conexão cair sem aviso (energia, rede, travamento),
    # o BROKER publica esta mensagem em nome do dispositivo. Retida, para quem
    # assinar depois saber na hora que a máquina está fora do ar.
    cliente.will_set(topico("status"), payload_status("offline", "conexao_perdida"), qos=1, retain=True)
    while True:
        try:
            cliente.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            log(f"conectado ao broker {MQTT_HOST}:{MQTT_PORT}")
            return cliente
        except OSError as erro:
            log(f"broker indisponível ({erro}); tentando de novo em 2 s...")
            time.sleep(2)


def main():
    validar_configuracao()
    maquina = MaquinaSimulada(MAQUINA_ID, TIPO_PRODUTO, DEGRADANDO, np.random.default_rng(),
                              ESCALA_DESGASTE, DERIVA_TORQUE, ATRASO_DEGRADACAO)
    cliente = conectar()

    def publicar_evento(evento, detalhe):
        payload = {"maquina_id": MAQUINA_ID, "ts": time.time(), "evento": evento, "detalhe": detalhe}
        cliente.publish(topico("evento"), json.dumps(payload), qos=1)

    # O callback roda na thread de rede do MQTT: ele só enfileira o comando, e o
    # laço principal o executa (uma única thread mexe na máquina e publica).
    comandos: queue.Queue = queue.Queue()

    def ao_receber_comando(_cliente, _userdata, msg):
        try:
            comandos.put(json.loads(msg.payload))
        except ValueError:
            log("comando inválido ignorado")

    def ao_conectar(cli, _userdata, _flags, _reason_code, _properties):
        cli.subscribe(topico("comando"), qos=1)  # só as ordens desta máquina
        cli.publish(topico("status"), payload_status("online"), qos=1, retain=True)

    cliente.on_connect = ao_conectar
    cliente.on_message = ao_receber_comando
    cliente.loop_start()  # rede MQTT em thread separada

    def desligar(_sinal, _frame):
        # Desligamento normal (ex.: docker compose stop): avisa offline por conta
        # própria e desconecta limpo. Nesse caso o broker NÃO usa o Last Will.
        log("desligando")
        cliente.publish(topico("status"), payload_status("offline", "desligamento"),
                        qos=1, retain=True).wait_for_publish(timeout=2)
        cliente.disconnect()
        cliente.loop_stop()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, desligar)
    signal.signal(signal.SIGINT, desligar)

    log(f"em operação (tipo {TIPO_PRODUTO}{', DEGRADANDO' if DEGRADANDO else ''})")
    while True:
        while not comandos.empty():
            if comandos.get().get("acao") == "manutencao":
                maquina.manutencao()
                log("manutenção preventiva realizada (comando da plataforma)")
                publicar_evento("manutencao", "preventiva")

        if maquina.parada_restante > 0:  # máquina quebrada, sem telemetria
            maquina.parada_restante -= 1
            if maquina.parada_restante == 0:
                maquina.manutencao()
                log("manutenção corretiva concluída, máquina voltou a operar")
                publicar_evento("manutencao", "corretiva")
        else:
            leitura = maquina.ler_sensores()
            cliente.publish(topico("telemetria"), json.dumps(leitura))

            modos = maquina.falhas_fisicas(leitura)
            if modos:
                log(f"FALHA REAL: {modos}. Máquina parada.")
                publicar_evento("falha", ",".join(modos))
                maquina.parada_restante = LEITURAS_PARADA
        time.sleep(INTERVALO_S)


if __name__ == "__main__":
    main()
