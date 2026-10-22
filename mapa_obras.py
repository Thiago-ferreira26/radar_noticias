"""Mapa de Obras Cordeiro — app separado do Radar de notícias (mesmo banco e mesmo Bitrix).

    streamlit run mapa_obras.py
Páginas: / (painel com mapa, fichas, Bitrix e Excel) e /tv (carrossel em tela cheia para a TV).
Com st.navigation, a pasta pages/ (páginas do Radar) não entra neste app.
"""
import streamlit as st

st.navigation(
    [st.Page("obras_app/painel.py", title="Mapa de Obras", icon="🏗️", default=True),
     st.Page("obras_app/tv.py", title="Modo TV", icon="📺", url_path="tv")],
    position="hidden",
).run()
