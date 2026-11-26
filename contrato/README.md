# Contrato de comunicação (MQTT)

Este é o **único acoplamento** entre o chão de fábrica (`dispositivos/`) e a plataforma (`plataforma/`). Qualquer dispositivo que siga este contrato (o simulador, um ESP32 ou um CLP com gateway MQTT) funciona sem mudar nada na plataforma.

| Tópico | Quem publica | QoS | Schema |
|---|---|---|---|
| `fabrica/maquinas/<id>/telemetria` | dispositivo | 0 | [`telemetria.schema.json`](telemetria.schema.json) |
| `fabrica/maquinas/<id>/evento` | dispositivo | 1 | [`evento.schema.json`](evento.schema.json) |
| `fabrica/maquinas/<id>/status` | dispositivo **ou broker** (Last Will) | 1, **retido** | [`status.schema.json`](status.schema.json) |
| `fabrica/maquinas/<id>/comando` | plataforma | 1 | [`comando.schema.json`](comando.schema.json) |
| `fabrica/alertas` | plataforma | 1 | [`alerta.schema.json`](alerta.schema.json) |

- `<id>` é o identificador da máquina e deve ser igual ao campo `maquina_id` da mensagem.
- Payload em JSON (UTF-8). Unidades no SI: temperatura em kelvin, torque em N·m.
- A telemetria usa QoS 0 (perder uma leitura entre centenas não importa, e isso economiza banda). Eventos, status, comandos e alertas usam QoS 1, porque precisam chegar.
- A plataforma **valida** toda mensagem recebida contra estes schemas e descarta (com log) o que estiver fora do contrato.

### Status de conexão e Last Will

Todo dispositivo deve, **antes** de conectar, registrar no broker um *Last Will* ("testamento") com `{"status": "offline", "motivo": "conexao_perdida"}` no seu tópico `status`, retido. Depois:

| Situação | Quem publica | Mensagem |
|---|---|---|
| conectou | dispositivo | `{"status": "online"}` |
| desligamento normal | dispositivo | `{"status": "offline", "motivo": "desligamento"}` |
| queda sem aviso (energia, rede, travamento) | **o broker**, ao detectar a queda | `{"status": "offline", "motivo": "conexao_perdida"}` |

Como as mensagens são retidas, qualquer assinante que conectar depois recebe na hora o último status de cada máquina.

Exemplo de telemetria:

```json
{
  "maquina_id": "M-03",
  "ts": 1764000000.12,
  "tipo": "L",
  "temp_ar_k": 300.4,
  "temp_processo_k": 310.5,
  "rotacao_rpm": 1302.7,
  "torque_nm": 55.21,
  "desgaste_min": 160.0
}
```
