"""Serviço de ingestão + inferência em tempo real (streaming em micro-lotes).

O callback MQTT apenas enfileira as mensagens. A cada LOTE_S segundos o laço
principal processa tudo o que chegou de uma vez (padrão "micro-batch", o mesmo
do Spark Streaming): uma única predição vetorizada e uma única gravação no
banco por lote. Isso mantém o serviço em tempo real mesmo com muitas máquinas.

Para cada leitura:
  1. guarda a leitura numa janela deslizante por máquina (últimas N leituras)
  2. estima a tendência de cada sensor (regressão linear na janela) e PROJETA
     o estado da máquina HORIZONTE_LEITURAS à frente
  3. o modelo de IA calcula:
       prob_atual  probabilidade de falha no estado atual
       risco       probabilidade de falha no estado projetado (é isso que torna
                   a manutenção PREDITIVA: o alerta sai antes da falha)
  4. grava tudo no banco; se o risco (média móvel) passar do limiar, identifica
     o tipo de falha provável e publica um alerta em `fabrica/alertas`
"""
import json
import queue
import time
from collections import defaultdict, deque

import joblib
import numpy as np
import pandas as pd

from plataforma.comum import armazenamento, config, contrato, features, mqtt_util

LOTE_S = 0.5  # intervalo entre micro-lotes

# Faixa física válida de cada sensor (a projeção não pode sair dela)
LIMITES = {
    "temp_ar_k": (290, 310), "temp_processo_k": (300, 320), "rotacao_rpm": (800, 2900),
    "torque_nm": (3, 80), "desgaste_min": (0, 253),
}


class EstadoMaquina:
    def __init__(self):
        self.janela = deque(maxlen=config.JANELA_TENDENCIA)
        self.riscos = deque(maxlen=config.JANELA_MEDIA)
        self.em_alerta = False


def projetar(janela) -> dict:
    """Extrapola a tendência linear de cada sensor HORIZONTE_LEITURAS à frente."""
    ultima = dict(janela[-1])
    if len(janela) < config.JANELA_TENDENCIA:
        return ultima  # ainda sem histórico suficiente: usa o estado atual
    x = np.arange(len(janela))
    x_futuro = len(janela) - 1 + config.HORIZONTE_LEITURAS
    for sensor in features.SENSORES:
        inclinacao, intercepto = np.polyfit(x, [l[sensor] for l in janela], 1)
        ultima[sensor] = float(np.clip(inclinacao * x_futuro + intercepto, *LIMITES[sensor]))
    return ultima


class ServicoInferencia:
    def __init__(self, artefato, con, cliente):
        self.modelo_falha = artefato["modelo_falha"]
        self.modelo_tipo = artefato["modelo_tipo"]
        self.con = con
        self.cliente = cliente
        self.estados: dict[str, EstadoMaquina] = defaultdict(EstadoMaquina)

    def processar_lote(self, mensagens: list[tuple[str, dict]]):
        # Passo 1 (em ordem de chegada): atualiza janelas e calcula projeções
        operacoes, linhas_modelo = [], []
        for tipo, dados in mensagens:
            estado = self.estados[dados["maquina_id"]]
            if tipo == "status":
                operacoes.append(("status", dados, None))  # não afeta a IA, só o registro
            elif tipo == "evento":
                estado.janela.clear()  # após falha ou manutenção o histórico recomeça
                operacoes.append(("evento", dados, None))
            else:
                estado.janela.append(dados)
                operacoes.append(("leitura", dados, len(linhas_modelo)))
                linhas_modelo += [dados, projetar(estado.janela)]

        # Passo 2: UMA predição vetorizada para o lote inteiro
        if linhas_modelo:
            X = features.montar_features(pd.DataFrame(linhas_modelo))
            probs = self.modelo_falha.predict_proba(X)[:, 1]

        # Passo 3 (em ordem): risco, alertas e eventos
        leituras_db, alertas = [], []
        for tipo, dados, i in operacoes:
            estado = self.estados[dados["maquina_id"]]
            if tipo == "status":
                armazenamento.salvar_status(self.con, dados, dados["_recebido_em"])
                motivo = f" ({dados['motivo']})" if dados.get("motivo") else ""
                print(f"Status [{dados['maquina_id']}] {dados['status']}{motivo}")
                continue
            if tipo == "evento":
                estado.riscos.clear()
                estado.em_alerta = False
                armazenamento.salvar_evento(self.con, dados)
                print(f"Evento [{dados['maquina_id']}] {dados['evento']} ({dados.get('detalhe', '')})")
                continue

            prob_atual, prob_futura = float(probs[i]), float(probs[i + 1])
            estado.riscos.append(max(prob_atual, prob_futura))
            risco = sum(estado.riscos) / len(estado.riscos)
            leituras_db.append((dados, prob_atual, risco))

            # O alerta funciona como uma ordem de serviço: fica aberto até a
            # manutenção (ou a falha) ser registrada.
            if not estado.em_alerta and risco >= config.LIMIAR_ALERTA:
                estado.em_alerta = True
                modo = str(self.modelo_tipo.predict(X.iloc[[i + 1]])[0])
                alertas.append({
                    "ts": time.time(),
                    "maquina_id": dados["maquina_id"],
                    "risco": round(risco, 3),
                    "tipo_falha": modo,
                    "mensagem": f"Risco de falha {risco:.0%} - provável causa: {features.NOMES_FALHA.get(modo, modo)}",
                })

        armazenamento.salvar_leituras(self.con, leituras_db)
        for alerta in alertas:
            self.cliente.publish(config.TOPICO_ALERTAS, json.dumps(alerta), qos=1)
            armazenamento.salvar_alerta(self.con, alerta)
            print(f"ALERTA [{alerta['maquina_id']}] {alerta['mensagem']}")


def main():
    if not config.MODELO_PATH.exists():
        raise SystemExit(f"Modelo não encontrado em {config.MODELO_PATH}. "
                         "Rode antes: python -m plataforma.treino.treinar_modelo")
    artefato = joblib.load(config.MODELO_PATH)
    print(f"Modelo carregado (treinado com: {artefato['fonte_dados']})")

    fila: queue.Queue = queue.Queue()
    cliente = mqtt_util.conectar("servico-inferencia")

    def ao_conectar(cli, _userdata, _flags, _reason_code, _properties):
        # status é retido: ao (re)conectar recebemos na hora o último status de cada máquina
        cli.subscribe([(f"{config.TOPICO_BASE}/+/telemetria", 0), (f"{config.TOPICO_BASE}/+/evento", 1),
                       (f"{config.TOPICO_BASE}/+/status", 1)])

    descartadas = 0
    relogios_ruins: set[str] = set()  # máquinas com relógio dessincronizado (para logar uma vez só)

    def ao_receber(_cli, _userdata, msg):
        # Não confiamos no que chega da rede: valida contra o contrato (contrato/*.schema.json)
        nonlocal descartadas
        nome = msg.topic.rsplit("/", 1)[-1]  # telemetria | evento | status
        try:
            dados = json.loads(msg.payload)
        except ValueError:
            dados = None
        problemas = ["payload não é JSON"] if dados is None else contrato.erros(nome, dados)
        if not problemas and dados["maquina_id"] != msg.topic.split("/")[2]:
            problemas = ["maquina_id diferente do <id> do tópico"]
        if problemas:
            descartadas += 1
            print(f"Mensagem fora do contrato descartada ({msg.topic}): {problemas[:3]}")
            return
        agora = time.time()
        if nome == "status":
            dados["_recebido_em"] = agora
        elif abs(dados["ts"] - agora) > config.TOLERANCIA_RELOGIO_S:
            # relógio do dispositivo dessincronizado (ex.: sem NTP): usa o horário de recebimento
            if dados["maquina_id"] not in relogios_ruins:
                relogios_ruins.add(dados["maquina_id"])
                print(f"Relógio de {dados['maquina_id']} fora do horário ({dados['ts'] - agora:+.0f} s): "
                      "usando o horário de recebimento")
            dados["ts_dispositivo"], dados["ts"] = dados["ts"], agora
        else:
            relogios_ruins.discard(dados["maquina_id"])
        fila.put(("leitura" if nome == "telemetria" else nome, dados))

    cliente.on_connect = ao_conectar  # dispara ao receber o CONNACK (e em reconexões)
    cliente.on_message = ao_receber
    cliente.loop_start()  # rede MQTT em thread separada

    servico = ServicoInferencia(artefato, armazenamento.conectar(), cliente)
    print("Aguardando telemetria...")
    while True:
        inicio = time.monotonic()
        lote = []
        while not fila.empty():
            lote.append(fila.get())
        if lote:
            try:
                servico.processar_lote(lote)
            except Exception as erro:  # um lote ruim não pode derrubar o serviço
                print(f"Erro processando lote de {len(lote)} mensagens: {erro!r}")
        time.sleep(max(0.0, LOTE_S - (time.monotonic() - inicio)))


if __name__ == "__main__":
    main()
