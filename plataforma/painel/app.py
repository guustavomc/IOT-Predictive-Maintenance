"""Painel de monitoramento (Streamlit).

Rode (da raiz do repositório) com:  streamlit run plataforma/painel/app.py
"""
import json
import sys
import time
from pathlib import Path

# o Streamlit roda o arquivo como script: coloca a raiz do repo no path para `from plataforma ...`
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import altair as alt
import pandas as pd
import paho.mqtt.publish as publish
import streamlit as st

from plataforma.comum import armazenamento, config

st.set_page_config(page_title="Manutenção Preditiva", page_icon="🏭", layout="wide")
st.title("🏭 Manutenção Preditiva Industrial: IoT + IA")

janela_min = st.sidebar.slider("Janela de tempo (min)", 1, 30, 5)
NIVEL_ATENCAO = config.LIMIAR_ALERTA * 0.6


def para_hora(serie_ts: pd.Series) -> pd.Series:
    return pd.to_datetime(serie_ts, unit="s", utc=True).dt.tz_convert(config.FUSO)


def carregar(janela_min: int):
    con = armazenamento.conectar()
    try:
        desde = time.time() - janela_min * 60
        leituras = pd.read_sql_query("SELECT * FROM leituras WHERE ts >= ? ORDER BY ts", con, params=(desde,))
        alertas = pd.read_sql_query("SELECT * FROM alertas ORDER BY ts", con)
        eventos = pd.read_sql_query("SELECT * FROM eventos ORDER BY ts", con)
        conexoes = pd.read_sql_query("SELECT * FROM conexoes ORDER BY ts", con)
    finally:
        con.close()
    for df in (leituras, alertas, eventos):
        df["hora"] = para_hora(df["ts"])
    # último status de conexão de cada máquina (online/offline)
    ultimo_status = conexoes.groupby("maquina_id").tail(1).set_index("maquina_id")
    return leituras, alertas, eventos, ultimo_status


def antecedencia_alertas(alertas: pd.DataFrame, eventos: pd.DataFrame) -> pd.DataFrame:
    """Para cada falha real: quantos segundos antes a IA alertou? (validação da solução)"""
    linhas = []
    for _, falha in eventos[eventos["evento"] == "falha"].iterrows():
        anteriores = eventos[(eventos["maquina_id"] == falha["maquina_id"]) & (eventos["ts"] < falha["ts"])]
        inicio_ciclo = anteriores["ts"].max() if len(anteriores) else 0
        a = alertas[(alertas["maquina_id"] == falha["maquina_id"])
                    & (alertas["ts"] > inicio_ciclo) & (alertas["ts"] <= falha["ts"])]
        linhas.append({
            "máquina": falha["maquina_id"],
            "falha em": falha["hora"].strftime("%H:%M:%S"),
            "modo real": falha["detalhe"],
            "alertado?": "sim" if len(a) else "NÃO",
            "antecedência (s)": round(falha["ts"] - a["ts"].min(), 1) if len(a) else None,
        })
    return pd.DataFrame(linhas)


def enviar_manutencao(maquina_id: str):
    publish.single(
        config.topico(maquina_id, "comando"), json.dumps({"acao": "manutencao"}),
        qos=1, hostname=config.MQTT_HOST, port=config.MQTT_PORT,
    )


@st.fragment(run_every=2)
def ao_vivo():
    leituras, alertas, eventos, ultimo_status = carregar(janela_min)
    if leituras.empty:
        st.info("Aguardando telemetria... (as máquinas e o serviço de inferência estão rodando?)")
        return

    # --- Status por máquina ----------------------------------------------
    ultimas = leituras.sort_values("ts").groupby("maquina_id").tail(1).set_index("maquina_id").sort_index()
    paradas = set()
    for mid, grupo in eventos.groupby("maquina_id"):
        if grupo.iloc[-1]["evento"] == "falha":
            paradas.add(mid)

    agora = time.time()
    colunas = st.columns(len(ultimas))
    for col, (mid, ult) in zip(colunas, ultimas.iterrows()):
        p = ult["risco"]
        silencio_s = agora - ult["ts"]
        conexao = ultimo_status.loc[mid] if mid in ultimo_status.index else None
        offline = conexao is not None and conexao["status"] == "offline"
        sem_sinal = offline or (mid not in paradas and silencio_s > config.SEM_SINAL_S)
        if offline:
            # o broker (Last Will) ou o próprio dispositivo avisou que caiu
            motivo = {"conexao_perdida": "conexão perdida (Last Will)",
                      "desligamento": "desligada"}.get(conexao["motivo"], conexao["motivo"])
            status = f"🔌 OFFLINE: {motivo}, há {agora - conexao['ts']:.0f} s"
        elif mid in paradas:
            status = "⛔ PARADA (falha)"
        elif sem_sinal:
            # conectado, mas sem mandar telemetria (ex.: sensor travado)
            status = f"⚪ Sem sinal há {silencio_s:.0f} s"
        elif p >= config.LIMIAR_ALERTA:
            status = "🔴 ALERTA"
        elif p >= NIVEL_ATENCAO:
            status = "🟡 Atenção"
        else:
            status = "🟢 Normal"
        with col:
            st.metric(f"{mid} (tipo {ult['tipo']})", f"{p:.0%}", help="Probabilidade de falha (média móvel)")
            st.caption(status)
            if st.button("🔧 Manutenção", key=f"man_{mid}", disabled=mid in paradas or sem_sinal or offline):
                try:
                    enviar_manutencao(mid)
                    st.toast(f"Ordem de manutenção enviada para {mid}")
                except OSError as erro:
                    st.error(f"Falha ao enviar comando MQTT: {erro}")

    # --- Gráficos ---------------------------------------------------------
    st.subheader("Risco de falha previsto pela IA (linha vermelha = limiar de alerta)")
    linhas = alt.Chart(leituras).mark_line().encode(
        x=alt.X("hora:T", title=None),
        y=alt.Y("risco:Q", title="risco", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
        color=alt.Color("maquina_id:N", title="máquina"),
    )
    limiar = alt.Chart(pd.DataFrame({"y": [config.LIMIAR_ALERTA]})).mark_rule(
        color="red", strokeDash=[6, 4]).encode(y="y:Q")
    st.altair_chart(linhas + limiar, width="stretch")

    maquinas = sorted(leituras["maquina_id"].unique())
    if st.session_state.get("maquina_sel") not in maquinas:
        # padrão: a máquina que a IA considera mais arriscada na janela
        st.session_state["maquina_sel"] = leituras.loc[leituras["risco"].idxmax(), "maquina_id"]
    maquina = st.selectbox("Sensores da máquina", maquinas, key="maquina_sel")
    dm = leituras[leituras["maquina_id"] == maquina].copy()
    dm["delta_temp_k"] = dm["temp_processo_k"] - dm["temp_ar_k"]
    dm["desgaste_x_torque"] = dm["desgaste_min"] * dm["torque_nm"]
    g1, g2, g3, g4 = st.columns(4)
    g1.line_chart(dm, x="hora", y="torque_nm", height=180)
    g2.line_chart(dm, x="hora", y="desgaste_min", height=180)
    g3.line_chart(dm, x="hora", y="rotacao_rpm", height=180)
    g4.line_chart(dm, x="hora", y="desgaste_x_torque", height=180)

    # --- Alertas, eventos e validação --------------------------------------
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🚨 Alertas da IA")
        if alertas.empty:
            st.write("Nenhum alerta até agora.")
        else:
            st.dataframe(
                alertas.sort_values("ts", ascending=False)[["hora", "maquina_id", "risco", "tipo_falha", "mensagem"]],
                hide_index=True, height=220,
            )
    with c2:
        st.subheader("📋 Eventos (falhas e manutenções)")
        if eventos.empty:
            st.write("Nenhum evento até agora.")
        else:
            st.dataframe(eventos.sort_values("ts", ascending=False)[["hora", "maquina_id", "evento", "detalhe"]],
                         hide_index=True, height=220)

    st.subheader("✅ Validação: a IA avisou antes da falha?")
    tabela = antecedencia_alertas(alertas, eventos)
    preventivas = len(eventos[(eventos["evento"] == "manutencao") & (eventos["detalhe"] == "preventiva")])
    k1, k2, k3 = st.columns(3)
    k1.metric("Falhas reais", len(tabela))
    k2.metric("Falhas alertadas a tempo", int((tabela["alertado?"] == "sim").sum()) if len(tabela) else 0)
    k3.metric("Manutenções preventivas (falhas evitadas)", preventivas)
    if len(tabela):
        st.dataframe(tabela, hide_index=True)


ao_vivo()
