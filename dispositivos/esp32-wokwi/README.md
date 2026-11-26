# M-06: ESP32 com sensores reais (simulado no Wokwi)

Uma sexta máquina, agora com **firmware de microcontrolador de verdade**: um ESP32 com sensores físicos, rodando no simulador [Wokwi](https://wokwi.com). Ele segue o mesmo [contrato MQTT](../../contrato/README.md) das máquinas em Python, então **a plataforma não precisa de nenhuma mudança**: para ela, a M-06 é só mais uma máquina.

## O circuito

| Componente | Pino | Papel |
|---|---|---|
| DHT22 | GPIO 15 | temperatura do ar |
| Termistor NTC | GPIO 32 | temperatura do processo |
| Potenciômetro | GPIO 34 | célula de carga, torque (0–80 N·m) |
| Potenciômetro | GPIO 35 | tacômetro, rotação (1000–2500 rpm) |
| Botão azul | GPIO 4 | troca de ferramenta feita pelo operador |
| LED verde | GPIO 27 | conectado à plataforma |
| LED vermelho | GPIO 26 | **alerta da IA para esta máquina** |

O desgaste da ferramenta é contado pelo próprio firmware (+2 min por leitura, acelerado para a demo) e volta a zero quando a ferramenta é trocada, seja pelo botão ou por uma ordem de manutenção do painel.

## Como a mensagem chega à plataforma

O Wokwi no navegador só alcança a internet, não o seu `localhost`. Por isso o ESP32 publica num **broker público** (`broker.hivemq.com`), com um prefixo único nos tópicos, e um **bridge do Mosquitto local** espelha só os tópicos da M-06, tirando o prefixo:

```
ESP32 (Wokwi) ──► broker.hivemq.com ──► bridge do Mosquitto local ──► plataforma
                  iotpm-d38091/fabrica/...          fabrica/...
```

O bridge funciona nos dois sentidos: telemetria, eventos e status entram; comandos e alertas saem. É assim que o botão 🔧 do painel e o LED vermelho funcionam.

> O broker público é aberto: qualquer pessoa que souber o prefixo pode ler esses tópicos. Para dados simulados de uma demonstração, tudo bem. Em produção, o caminho seria um broker próprio com autenticação e TLS.

## Passo a passo

**1. Subir a plataforma com o bridge** (na raiz do repositório):

```powershell
docker compose -f docker-compose.yml -f docker-compose.wokwi.yml up --build
```

(Se a porta 1883 estiver ocupada, comece com `$env:MQTT_PORTA_HOST = "1884";`.)

**2. Montar o projeto no Wokwi:**

1. Abra https://wokwi.com/projects/new/esp32 (não precisa de login para simular).
2. Na aba `sketch.ino`, cole o conteúdo de [`sketch.ino`](sketch.ino).
3. Na aba `diagram.json`, cole o conteúdo de [`diagram.json`](diagram.json). O circuito aparece montado.
4. Em **Library Manager → +**, adicione `PubSubClient`. Vai aparecer a aba `libraries.txt`. Nela, cole o conteúdo de [`libraries.txt`](libraries.txt) (que adiciona também `ArduinoJson` e `DHT sensor library for ESPx`).
5. Aperte ▶. No monitor serial: `Wi-Fi ok`, `NTP ok`, `broker MQTT ok` e, em seguida, uma leitura JSON por segundo.

> Dica: faça login no Wokwi e salve o projeto para não precisar colar tudo de novo. **Deixe a aba do Wokwi visível**: em aba de fundo o navegador desacelera a simulação.

**3. Ver no painel:** a M-06 aparece em http://localhost:8501 ao lado das outras.

## Roteiro de demonstração

1. **Operação normal:** com os valores iniciais (27 °C, 37 °C, ~40 N·m, ~1540 rpm), o risco fica perto de 0%.
2. **Sobrecarga:** gire o potenciômetro de **torque para ~60 N·m** e o de **rotação para ~1200 rpm** (numa máquina real a rotação cai quando a carga sobe). Com o desgaste da ferramenta subindo, o risco cresce, a IA alerta **"Sobrecarga (desgaste x torque)"** e o **LED vermelho do ESP32 acende**.
3. **Manutenção:** clique em 🔧 na M-06 do painel. O comando atravessa o bridge, o ESP32 zera o desgaste, apaga o LED vermelho e o painel registra a manutenção preventiva. Ou aperte o botão azul do circuito, que é o operador trocando a ferramenta na máquina.
4. **Potência fora da faixa:** torque em ~60 N·m mas rotação mantida em ~1540 rpm. A potência passa de 9 kW e a IA alerta **"Potência fora da faixa"** quase na hora, sem depender do desgaste.
5. **Last Will:** pare a simulação (■). Alguns segundos depois o broker público publica `offline`, que atravessa o bridge, e o painel mostra a M-06 como 🔌 **OFFLINE: conexão perdida (Last Will)**.

## Limitações conhecidas

- A biblioteca `PubSubClient` só **publica** com QoS 0. O contrato pede QoS 1 para eventos e status, mas aqui o Last Will e as assinaturas (comandos e alertas) usam QoS 1.
- Se o NTP não sincronizar, o firmware segue mesmo assim, e a plataforma usa o horário de recebimento das mensagens enquanto o relógio do dispositivo estiver errado.
- Para usar outro prefixo, troque `iotpm-d38091` em [`sketch.ino`](sketch.ino) **e** em [`mosquitto/mosquitto-wokwi.conf`](../../mosquitto/mosquitto-wokwi.conf).
