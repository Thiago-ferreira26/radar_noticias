"""Modo TV do Radar Cordeiro — carrossel em tela cheia para a TV (rota /tv).

    http://<servidor>:8501/tv
Parâmetros opcionais na URL: ?segundos=18&capa=12&max=24&recarregar=10
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from radar.tvdeck import build_deck

st.set_page_config(page_title="Radar Cordeiro · TV", page_icon="📺", layout="wide",
                   initial_sidebar_state="collapsed")

# Esconde toda a interface do Streamlit e estica o carrossel para a tela inteira.
st.markdown(
    """<style>
    header, footer, [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"], [data-testid="stDecoration"], [data-testid="stStatusWidget"]{display:none !important;}
    html, body, .stApp, [data-testid="stAppViewContainer"]{background:#0b1f1e !important; overflow:hidden !important;}
    .block-container{padding:0 !important; max-width:100% !important;}
    iframe{position:fixed !important; inset:0 !important; width:100vw !important; height:100vh !important;
      border:0 !important; z-index:1000;}
    </style>""",
    unsafe_allow_html=True,
)


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(st.query_params.get(name, default))))
    except ValueError:
        return default


cfg = {
    "opMs": _int("segundos", 18, 5, 120) * 1000,
    "coverMs": _int("capa", 12, 5, 120) * 1000,
    "refreshMin": _int("recarregar", 10, 1, 240),  # recarrega os dados ao voltar para a capa após N minutos
}
deck = build_deck(max_ops=_int("max", 24, 1, 60))

template = (Path(__file__).resolve().parent.parent / "radar" / "tv.html").read_text(encoding="utf-8")
page = (template
        .replace("__DATA__", json.dumps(deck, ensure_ascii=False).replace("</", "<\\/"))
        .replace("__CFG__", json.dumps(cfg)))
components.html(page, height=1080, scrolling=False)
