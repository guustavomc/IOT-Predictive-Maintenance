"""Funções auxiliares de MQTT compartilhadas pelos serviços."""
import time

import paho.mqtt.client as mqtt

from plataforma.comum import config


def conectar(client_id: str) -> mqtt.Client:
    """Cria um cliente MQTT e conecta ao broker, tentando de novo até conseguir.

    (No docker-compose o broker pode subir alguns segundos depois dos serviços.)
    """
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    while True:
        try:
            cliente.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
            print(f"[{client_id}] conectado ao broker {config.MQTT_HOST}:{config.MQTT_PORT}")
            return cliente
        except OSError as erro:
            print(f"[{client_id}] broker indisponível ({erro}); tentando de novo em 2 s...")
            time.sleep(2)
