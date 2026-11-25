"""Validação das mensagens MQTT contra os JSON Schemas de contrato/.

A plataforma não confia no que chega da rede: toda mensagem é validada e o que
estiver fora do contrato é descartado com log.
"""
import json

from jsonschema import Draft202012Validator

from plataforma.comum import config


def _carregar(nome: str) -> Draft202012Validator:
    schema = json.loads((config.CONTRATO_DIR / f"{nome}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


VALIDADORES = {nome: _carregar(nome) for nome in ("telemetria", "evento", "comando", "alerta")}


def erros(nome: str, mensagem: dict) -> list[str]:
    """Lista de violações do contrato (vazia se a mensagem é válida)."""
    return [f"{'/'.join(map(str, e.path)) or '(raiz)'}: {e.message}"
            for e in VALIDADORES[nome].iter_errors(mensagem)]
