"""Treina os modelos de IA com dados históricos (dataset AI4I 2020).

Gera dois modelos:
  1. modelo_falha  probabilidade de a máquina estar em condição de falha (binário)
  2. modelo_tipo   qual o modo de falha mais provável (TWF/HDF/PWF/OSF/...)

Saídas: modelos/modelo.joblib e modelos/metricas.json
"""
import json

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score
from sklearn.model_selection import train_test_split

from src import config, fisica


def carregar_dados() -> tuple[pd.DataFrame, str]:
    if config.DATASET_PATH.exists():
        df = pd.read_csv(config.DATASET_PATH).rename(columns=fisica.COLUNAS_AI4I)
        return df, f"AI4I 2020 ({config.DATASET_PATH.name})"
    print(f"AVISO: {config.DATASET_PATH} não encontrado. Usando dataset SINTÉTICO no formato AI4I.")
    print("       Para o relatório, baixe o dataset real (instruções no README).")
    return fisica.gerar_dataset_sintetico(), "sintético (regras AI4I)"


def modo_principal(linha) -> str:
    for modo in fisica.MODOS_FALHA:
        if linha[modo] == 1:
            return modo
    return "RNF"  # no AI4I existem poucas falhas sem modo marcado


def main():
    df, fonte = carregar_dados()
    X = fisica.montar_features(df)
    y = df["falha"]
    print(f"Fonte: {fonte} | {len(df)} registros | taxa de falha: {y.mean():.2%}")

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)

    # class_weight compensa o desbalanceamento (poucas falhas vs. muitas leituras normais)
    modelo_falha = RandomForestClassifier(
        n_estimators=200, min_samples_leaf=3, class_weight="balanced_subsample",
        n_jobs=-1, random_state=42,
    )
    modelo_falha.fit(X_tr, y_tr)

    prob = modelo_falha.predict_proba(X_te)[:, 1]
    pred = (prob >= config.LIMIAR_ALERTA).astype(int)
    relatorio = classification_report(y_te, pred, target_names=["normal", "falha"], output_dict=True)
    print(classification_report(y_te, pred, target_names=["normal", "falha"]))
    print("Matriz de confusão [[VN, FP], [FN, VP]]:", confusion_matrix(y_te, pred).tolist())
    print(f"ROC AUC: {roc_auc_score(y_te, prob):.4f}")

    importancias = dict(sorted(
        zip(fisica.FEATURES, modelo_falha.feature_importances_.round(4).tolist()),
        key=lambda kv: -kv[1],
    ))
    print("Importância das features:", importancias)

    # Modelo de tipo de falha: treinado só com as leituras que falharam
    falhas = df[df["falha"] == 1]
    modelo_tipo = RandomForestClassifier(n_estimators=100, random_state=42)
    modelo_tipo.fit(fisica.montar_features(falhas), falhas.apply(modo_principal, axis=1))

    # Na inferência chega uma leitura por vez: paralelismo só atrapalha
    modelo_falha.n_jobs = 1

    config.MODELO_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"modelo_falha": modelo_falha, "modelo_tipo": modelo_tipo,
         "features": fisica.FEATURES, "fonte_dados": fonte},
        config.MODELO_PATH,
    )
    metricas = {
        "fonte_dados": fonte,
        "registros": len(df),
        "taxa_falha": round(float(y.mean()), 4),
        "limiar": config.LIMIAR_ALERTA,
        "roc_auc": round(float(roc_auc_score(y_te, prob)), 4),
        "matriz_confusao": confusion_matrix(y_te, pred).tolist(),
        "relatorio": relatorio,
        "importancia_features": importancias,
    }
    config.METRICAS_PATH.write_text(json.dumps(metricas, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Modelo salvo em {config.MODELO_PATH}")


if __name__ == "__main__":
    main()
