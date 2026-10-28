"""Caminhos, variáveis de ambiente e leitura/gravação do arquivo de termos de busca."""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

TZ = ZoneInfo(os.getenv("RADAR_TZ", "America/Fortaleza"))
DB_PATH = Path(os.getenv("RADAR_DB_PATH", BASE_DIR / "data" / "radar.db"))
TERMS_PATH = Path(os.getenv("RADAR_TERMS_PATH", BASE_DIR / "config" / "termos.yaml"))
LOG_DIR = BASE_DIR / "logs"

# Limite rígido de chamadas Exa por dia. O arquivo de termos pode reduzir, nunca aumentar.
EXA_HARD_LIMIT = 5


def secret(name: str) -> str | None:
    """Lê um segredo do .env ou, no Streamlit Community Cloud, de Settings → Secrets (NOME = "...")."""
    value = os.getenv(name, "").strip()
    if not value:
        try:
            import streamlit as st

            value = str(st.secrets.get(name, "")).strip()
        except Exception:  # sem streamlit ou sem secrets.toml (ex.: coleta pela linha de comando)
            value = ""
    return value or None


def exa_api_key() -> str | None:
    return secret("EXA_API_KEY")


def firecrawl_api_key() -> str | None:
    return secret("FIRECRAWL_API_KEY")


def bitrix_webhook_url() -> str | None:
    """URL base do webhook de entrada do Bitrix24, ex.: https://<conta>.bitrix24.com.br/rest/<id>/<token>/"""
    url = secret("BITRIX_WEBHOOK_URL")
    return url.rstrip("/") + "/" if url else None


def now() -> datetime:
    return datetime.now(TZ)


def today() -> date:
    return now().date()


DEFAULTS = {
    "exa": {"limite_diario": EXA_HARD_LIMIT, "dias_retroativos": 7, "resultados_por_busca": 10},
    "ddg": {"regiao": "br-pt", "periodo": "w", "resultados_por_busca": 15, "pausa_segundos": 2.0},
    # Firecrawl: cada busca consome créditos (~2 por 10 notícias); o limite diário controla o gasto.
    "firecrawl": {"ativo": True, "limite_diario": 10, "resultados_por_busca": 10, "periodo": "w"},
    "classificacao": {
        "ufs_prioritarias": ["CE", "PA"],
        "ufs_atuacao": ["MA", "PI", "RN", "PB", "PE", "AL", "SE", "BA"],
        "porte_relevante_milhoes": 100,
    },
    "excluir_se_contiver": [],
    # Fontes diretas por RSS (sem custo de API): [{nome, url, tema, ativo}]
    "fontes_rss": [],
    "rss": {"dias_retroativos": 14},
    # Nota 0–10 (radar/score.py): peso máximo de cada critério; os pesos são reescalados para somar 10.
    "nota": {"pesos": {"demanda": 2.5, "fase": 2.5, "regiao": 1.5, "contato": 1.5, "porte": 1.0, "prazo": 1.0}},
    "fontes_nao_incluidas": [],  # avaliadas e não usadas como feed: [{nome, url, motivo}]
    "temas": [],
}


def load_config() -> dict:
    cfg = {k: (v.copy() if isinstance(v, dict) else list(v)) for k, v in DEFAULTS.items()}
    if TERMS_PATH.exists():
        with open(TERMS_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for key, value in data.items():
            if isinstance(cfg.get(key), dict) and isinstance(value, dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    limit = int(cfg["exa"].get("limite_diario", EXA_HARD_LIMIT))
    cfg["exa"]["limite_diario"] = max(0, min(limit, EXA_HARD_LIMIT))
    return cfg


def save_config(cfg: dict) -> None:
    TERMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TERMS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=120)


def iter_terms(cfg: dict, only_active: bool = True):
    """Gera dicts {tema, texto, exa, prioridade, ativo} para cada termo configurado."""
    for theme in cfg.get("temas", []) or []:
        for term in theme.get("termos", []) or []:
            if isinstance(term, str):
                term = {"texto": term}
            item = {
                "tema": theme.get("nome", "Geral"),
                "texto": str(term.get("texto", "")).strip(),
                "exa": bool(term.get("exa", False)),
                "firecrawl": bool(term.get("firecrawl", False)),
                "prioridade": int(term.get("prioridade", 3)),
                "ativo": bool(term.get("ativo", True)),
            }
            if not item["texto"] or (only_active and not item["ativo"]):
                continue
            yield item
