"""Mapa de Obras (rota /obras): obras do Obras Online no mapa, com envio ao Bitrix, Excel e Modo TV.

O mapa e as fichas são o painel "mapa_obras_cordeiro-PAINEL.html" (radar/obras.html), alimentado pelo banco.
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from radar import auth, config, crm, db, export, obras, ui

st.set_page_config(page_title="Mapa de Obras · Radar Cordeiro", page_icon="🏗️", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)
ui.disable_browser_translation()
try:
    db.init_db()
except db.DatabaseConnectionError as exc:
    st.error("**Banco de dados indisponível**\n\n" + str(exc).replace("\n", "  \n"))
    st.stop()
if flash := st.session_state.pop("obras_flash", None):
    st.toast(flash)


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


@st.cache_data(ttl=60, show_spinner=False)
def load() -> list[dict]:
    return obras.sort_for_tv(obras.load_obras())


@st.cache_data(ttl=30, show_spinner=False)
def load_sent() -> dict:
    return crm.sent_by_obra()


def refresh() -> None:
    load.clear()
    load_sent.clear()


lista = load()
last = obras.last_import()
today_key = config.today().isoformat()
html(ui.header([
    (f"{len(lista)}", "Obras monitoradas", False),
    (f"{sum(o.get('status') == obras.EM_CONSTRUCAO for o in lista)}", "Em construção", False),
    (f"{sum(o['daysTerm'] is not None and 0 <= o['daysTerm'] <= 60 for o in lista)}", "Fase termina em até 60 dias", True),
    (ui.fmt_date(last["imported_at"], True) if last else "—", "Última importação", False),
]))
c_back, c_tv, _, c_admin = st.columns([2.2, 3, 2.8, 2], vertical_alignment="center")
c_back.page_link("app.py", label="Radar de notícias", icon="📡")
c_tv.page_link("pages/tv_obras.py", label="Abrir Modo TV · Mapa de Obras", icon="📺")
with c_admin:
    auth.login_widget()
is_admin = auth.is_admin()

if not lista:
    html(ui.empty("Nenhuma obra na base ainda. Entre como administrador e importe o "
                  "mapa_obras_cordeiro-PAINEL.html no fim desta página."))
else:
    # Painel original (mapa, filtros e fichas), com os dados do banco.
    components.html(obras.panel_html(lista, ui.NO_TRANSLATE_JS), height=2400, scrolling=True)

    # ------------------------------------------------------------ Bitrix e Excel
    html(ui.section_title("Enviar obra para o Bitrix", len(load_sent())))
    st.caption("Escolha a obra e o responsável: o painel cria um lead com o código IM-OBR-<código da obra>, "
               "a fase, as datas previstas e as empresas envolvidas.")
    sent = load_sent()
    by_cod = {o["cod"]: o for o in lista}

    def label(cod: str) -> str:
        o = by_cod[cod]
        mark = " · ✓ enviado" if cod in sent else ""
        return f"{o['im']} · {o.get('setor')} · {o.get('tipo')} · {o.get('cidade')}/{o.get('uf')} · fase até {o.get('pfase')}{mark}"

    c1, c2, c3 = st.columns([4.5, 2.5, 2], vertical_alignment="bottom")
    cod = c1.selectbox("Obra", list(by_cod), index=None, format_func=label, placeholder="Digite o código, cidade ou tipo…")
    if not crm.is_configured():
        c2.warning("Configure BITRIX_WEBHOOK_URL no .env (ou em Secrets no Streamlit Cloud).")
    else:
        user = c2.selectbox("Responsável no Bitrix", crm.users(), index=None, format_func=lambda u: u["nome"],
                            placeholder="Selecione o usuário")
        if c3.button("Confirmar envio", type="primary", disabled=not (cod and user), width="stretch"):
            with st.spinner("Enviando ao Bitrix…"):
                res = crm.send_obra_lead(by_cod[cod], user)
            if res["ok"]:
                st.session_state["obras_flash"] = f"✅ {res['message']}"
                load_sent.clear()
                st.rerun()
            st.error(f"Não foi possível enviar: {res['message']}")
    if cod and cod in sent:
        s = sent[cod]
        link = crm.lead_url(s["lead_id"])
        st.caption(f"Já enviada em {ui.fmt_date(s['sent_at'], True)} para **{s['assigned_name']}** "
                   f"(lead [#{s['lead_id']}]({link})). Enviar de novo cria outro lead." if link else
                   f"Já enviada em {ui.fmt_date(s['sent_at'], True)} para **{s['assigned_name']}**.")

    c_x, _ = st.columns([2, 6])
    c_x.download_button(
        "Baixar Excel das obras", data=lambda: export.obras_workbook_bytes(lista),
        file_name=f"mapa-obras-cordeiro-{today_key}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", on_click="ignore", width="stretch",
    )
    if sent:
        with st.expander(f"Obras já enviadas ao Bitrix ({len(sent)})"):
            st.dataframe(
                [{"Lead IM": by_cod[c]["im"] if c in by_cod else obras.ob_code({"cod": c}),
                  "Obra": f"{by_cod[c].get('tipo')} · {by_cod[c].get('cidade')}/{by_cod[c].get('uf')}" if c in by_cod else "(fora do último arquivo)",
                  "Responsável": s["assigned_name"], "Lead": crm.lead_url(s["lead_id"]),
                  "Enviado em": ui.fmt_date(s["sent_at"], True)} for c, s in sent.items()],
                hide_index=True, width="stretch", column_config={"Lead": st.column_config.LinkColumn("Lead")},
            )

# ------------------------------------------------------------------ importação (administrador)
if is_admin:
    html(ui.section_title("Atualizar obras", last["n_total"] if last else 0))
    folder = config.secret("OBRAS_PASTA")
    st.caption("Envie a versão nova do mapa_obras_cordeiro-PAINEL.html (ou um JSON com a lista de obras). "
               "A importação substitui a lista: obras que não estão no arquivo saem do painel e da TV, mas continuam "
               "no banco. " + (f"Atualização automática ligada: a coleta diária importa o arquivo mais recente de "
                               f"`{folder}`." if folder else
                               "Para atualizar sozinho todo dia, defina OBRAS_PASTA no .env com a pasta do arquivo."))
    up = st.file_uploader("Mapa de Obras (HTML ou JSON)", type=["html", "htm", "json"])
    c1, c2 = st.columns(2)
    if up is not None and c1.button("Importar obras", type="primary"):
        try:
            res = obras.import_obras(up.getvalue().decode("utf-8"), "manual", up.name)
        except (ValueError, UnicodeDecodeError) as exc:
            st.error(f"Arquivo não reconhecido: {exc}")
        else:
            refresh()
            st.session_state["obras_flash"] = (f"✅ {res['total']} obras: {res['novas']} novas, "
                                               f"{res['atualizadas']} atualizadas, {res['removidas']} removidas.")
            st.rerun()
    if folder and c2.button("Importar agora da pasta"):
        res = obras.auto_import("manual")
        refresh()
        st.session_state["obras_flash"] = ("Nenhum HTML de obras na pasta." if res is None else
                                           "Arquivo sem mudanças desde a última importação." if res.get("sem_mudanca")
                                           else f"✅ {res['total']} obras: {res['novas']} novas, "
                                                f"{res['atualizadas']} atualizadas, {res['removidas']} removidas.")
        st.rerun()
    hist = db.read_sql("SELECT imported_at, origem, file_name, n_total, n_new, n_updated, n_removed "
                       "FROM obras_imports ORDER BY id DESC LIMIT 30")
    if not hist.empty:
        st.dataframe(hist, hide_index=True, width="stretch",
                     column_config={"imported_at": "Quando", "origem": "Origem", "file_name": "Arquivo",
                                    "n_total": "Obras", "n_new": "Novas", "n_updated": "Atualizadas",
                                    "n_removed": "Removidas"})

html(ui.footer(f"Fonte: Obras Online · Última importação: {ui.fmt_date(last['imported_at'], True) if last else '—'}"))
