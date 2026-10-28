"""Painel Streamlit do Radar Cordeiro. Lê o SQLite alimentado pelo scheduler.

    streamlit run app.py
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from radar import auth, config, crm, db, dossier, export, images, ui
from radar.collector import add_from_url, run_collection
from radar.classify import CATEGORIES, has_relation

st.set_page_config(page_title="Radar Cordeiro", page_icon="📡", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)
ui.disable_browser_translation()  # evita o erro "removeChild" causado pelo tradutor automático do navegador
try:
    db.init_db()
except db.DatabaseConnectionError as exc:  # Supabase configurado, mas inacessível: mostra o motivo e para
    st.error("**Banco de dados indisponível**\n\n" + str(exc).replace("\n", "  \n"))
    st.caption("Confira SUPABASE_DB_URL em Settings → Secrets (Streamlit Cloud) ou no .env e recarregue a página.")
    st.stop()
if flash := st.session_state.pop("crm_flash", None):  # resultado do último envio ao Bitrix
    st.toast(flash)

POT_RANK = {p: i for i, p in enumerate(ui.POTENTIALS)}


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


@st.cache_data(ttl=60, show_spinner=False)
def load_news() -> pd.DataFrame:
    df = db.read_sql("SELECT * FROM news ORDER BY collected_at DESC")
    df["pot_rank"] = df["potential"].map(POT_RANK).fillna(9)
    df["sort_date"] = df["published_at"].fillna(df["collected_at"])
    df["uf_list"] = df["ufs"].fillna("").str.split(",")
    df["relevante"] = df["demand"].map(has_relation).astype(bool)
    df["repetida"] = df["duplicate_of"].notna() if "duplicate_of" in df else False  # mesma notícia em outro site
    df["antiga"] = df["antiga"].fillna(0).astype(bool) if "antiga" in df else False  # já enviada em newsletter
    df["lead_im"] = [ui.im_code(r) for r in df.to_dict("records")]
    # Ficha do executivo: pesquisada (importada da newsletter) ou preliminar gerada pelo roteiro padrão.
    researched = dossier.get_dossiers()
    accounts = dossier.get_accounts()
    fichas = [dossier.dossier_for(r, researched) for r in df.to_dict("records")]
    df["ficha"] = fichas
    df["ficha_texto"] = [dossier.as_text(r, f, accounts) for r, f in zip(df.to_dict("records"), fichas)]
    df["entrada"] = [f.get("priority") for f in fichas]
    df["fase"] = [f.get("phase") for f in fichas]
    df["executor"] = [f.get("executor") for f in fichas]
    df["ficha_origem"] = [f.get("origin") for f in fichas]
    imgs = images.images_by_news()
    df["images"] = [imgs.get(i, []) for i in df["id"]]
    return df


@st.cache_data(ttl=60, show_spinner=False)
def load_accounts() -> dict:
    return dossier.get_accounts()


@st.cache_data(ttl=30, show_spinner=False)
def load_sent() -> dict:
    return crm.sent_by_news()


@st.cache_data(ttl=30, show_spinner=False)
def load_runs(limit: int = 50) -> pd.DataFrame:
    return db.read_sql("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))


def refresh() -> None:
    load_news.clear()
    load_runs.clear()
    load_accounts.clear()
    load_sent.clear()


CARDS_PER_ROW = 3
DAY_LIMIT = 12  # cards por tema na Visão do dia antes do botão "Mostrar todas"


def crm_button(r: dict, key: str, sent: dict | None) -> None:
    """Botão do card: escolher o usuário do Bitrix, confirmar e criar o lead (crm.lead.add)."""
    label = f"✓ Enviado ao Bitrix · {sent['assigned_name']}" if sent else "Enviar para o Bitrix"
    with st.popover(label, width="stretch"):
        if sent:
            st.caption(f"Já enviado em {ui.fmt_date(sent['sent_at'], True)} para **{sent['assigned_name']}** "
                       f"(lead #{sent['lead_id']}). Enviar de novo cria outro lead.")
        if not crm.is_configured():
            st.warning("Configure BITRIX_WEBHOOK_URL no .env (ou em Secrets no Streamlit Cloud).")
            return
        user = st.selectbox("Responsável no Bitrix", crm.users(), index=None, format_func=lambda u: u["nome"],
                            placeholder="Selecione o usuário", key=f"{key}_user")
        st.caption(f"Título do lead: {r['title'][:120]}")
        if st.button("Confirmar envio", type="primary", disabled=user is None, key=f"{key}_send", width="stretch"):
            with st.spinner("Enviando ao Bitrix…"):
                res = crm.send_lead(r, r["ficha"], user)
            if res["ok"]:
                # Recarrega a página para o card já mostrar o ID do lead e o responsável.
                st.session_state["crm_flash"] = f"✅ {res['message']}"
                load_sent.clear()
                st.rerun()
            else:
                st.toast(f"❌ Não foi possível enviar: {res['message']}")
                st.error(res["message"])


def render_cards(df: pd.DataFrame, new_day: str | None = None, limit: int | None = None, key: str = "c") -> None:
    rows = (df.head(limit) if limit else df).to_dict("records")
    accounts = load_accounts()
    sent = load_sent()
    for start in range(0, len(rows), CARDS_PER_ROW):
        cols = st.columns(CARDS_PER_ROW, gap="small")
        for col, r in zip(cols, rows[start:start + CARDS_PER_ROW]):
            with col:
                s = sent.get(r["id"])
                html(ui.card(r, is_new=(new_day is not None and r["collected_day"] == new_day),
                             ficha_html=ui.ficha(r, r["ficha"], accounts, r["ficha_texto"]), images=r["images"],
                             crm_html=ui.crm_block(s, crm.lead_url(s["lead_id"]) if s else None)))
                crm_button(r, f"{key}_crm_{r['id']}", s)


VERTICALS = ["Energia", "Minerais", "Infraestrutura"]
# Atalhos: os mesmos critérios dos indicadores "Novos hoje" e "Alta prioridade" do topo.
HIGHLIGHTS = ["Novas hoje", "Alta prioridade"]
HIGHLIGHT_COLORS = {"Novas hoje": "#1f5f5a", "Alta prioridade": "#c9761a"}
PRAZOS = ["Curto", "Médio", "Longo", "A confirmar"]
UF_PRIORITY = ["CE", "PA", "NE", "BR"]
FILTER_SUFFIXES = ("q", "d", "v", "p", "pz", "c", "uf", "fase", "exec")


def prazo_tier(value) -> str:
    m = re.match(r"^(Curto|Médio|Longo)", str(value or "").strip())
    return m.group(1) if m else "A confirmar"


def prazo_label(tier: str) -> str:
    y = config.today().year
    hint = {"Curto": f"{y}–{y + 1}", "Médio": f"{y + 2}–{y + 3}", "Longo": f"{y + 4}+"}.get(tier)
    return f"{tier} ({hint})" if hint else tier


def chip_row(label: str, options: list, key: str, fmt=None, dots: dict | None = None, big: bool = False):
    """Linha de chips no estilo da newsletter: rótulo em caixa alta à esquerda, chips à direita."""
    c_label, c_chips = st.columns([1.15, 8.85], vertical_alignment="center")
    css = ""
    if dots:  # bolinha colorida antes de cada chip, na ordem das opções
        size = 8 if big else 7
        css += (f".st-key-{key} button p::before{{content:'';display:inline-block;width:{size}px;height:{size}px;"
                "border-radius:50%;margin-right:6px;vertical-align:middle;}")
        css += "".join(f".st-key-{key} button:nth-of-type({i}) p::before{{background:{dots.get(o, '#7c8b86')};}}"
                       for i, o in enumerate(options, 1))
    if big:  # chips de Vertical: maiores, condensados e em caixa alta
        css += (f".st-key-{key} button p{{font-family:'IBM Plex Sans Condensed';font-weight:700;font-size:13.5px;"
                f"text-transform:uppercase;letter-spacing:.03em;}}"
                f".st-key-{key} button{{padding:6px 18px !important;border-width:1.5px !important;}}")
    # O <style> vai junto do rótulo para não criar um bloco (e espaçamento) a mais na página.
    c_label.markdown(f'<style>{css}</style><span class="rc-chiprow-label">{label}</span>', unsafe_allow_html=True)
    return c_chips.pills(label, options, selection_mode="multi", key=key, format_func=fmt,
                         label_visibility="collapsed") or []


def clear_filters(key: str) -> None:
    """Volta todos os filtros da barra ao estado inicial (atribuir o vazio também reseta o visual dos chips)."""
    empty = {"q": "", "fase": "Todas as fases", "exec": "Todas as situações"}
    for suffix in FILTER_SUFFIXES:
        st.session_state[f"{key}_{suffix}"] = empty.get(suffix, [])


def newsletter_filters(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """Barra de filtros da newsletter: busca, vertical, potencial, prazo, categoria, região, fase,
    empresa executora e o botão "Baixar Excel organizado" (exporta o resultado filtrado)."""
    c_q, c_clear = st.columns([8.5, 1.5], vertical_alignment="bottom")
    q = c_q.text_input("Buscar", placeholder="Buscar por palavra-chave, empresa, projeto ou Lead IM (ex.: IM-2026-0003)…", key=f"{key}_q",
                       label_visibility="collapsed")
    c_clear.button("Limpar filtros", key=f"{key}_clear", on_click=clear_filters, args=(key,), type="tertiary")

    destaques = chip_row("Destaques", HIGHLIGHTS, f"{key}_d", dots=HIGHLIGHT_COLORS, big=True)
    verts = chip_row("Vertical", VERTICALS, f"{key}_v", dots=ui.VERT_COLORS, big=True)
    pots = chip_row("Potencial", ui.POTENTIALS, f"{key}_p")
    html(ui.criteria())
    prazos = chip_row("Prazo da demanda", PRAZOS, f"{key}_pz", fmt=prazo_label)
    present = set(df["category"].dropna())
    cats = [c for c in CATEGORIES if c in present] + sorted(present - set(CATEGORIES))
    sel_cats = chip_row("Categoria", cats, f"{key}_c", dots=ui.CAT_COLORS)
    ufs_present = {u for lst in df["uf_list"] for u in lst if u}
    ufs = ([u for u in UF_PRIORITY if u in ufs_present]
           + sorted(ufs_present - set(UF_PRIORITY), key=lambda u: ui.UF_LABEL.get(u, u)))
    sel_ufs = chip_row("Região", ufs, f"{key}_uf", fmt=lambda u: ui.UF_LABEL.get(u, u))

    html('<hr class="rc-sep">')
    c1, c2, c3, c4, c5 = st.columns([1.3, 3.2, 1.5, 3.2, 2], vertical_alignment="center")
    c1.markdown("**Fase do projeto**")
    fase = c2.selectbox("Fase do projeto", ["Todas as fases"] + sorted(df["fase"].dropna().unique()),
                        key=f"{key}_fase", label_visibility="collapsed")
    c3.markdown("**Empresa executora**")
    executor = c4.selectbox("Empresa executora", ["Todas as situações"] + sorted(df["executor"].dropna().unique()),
                            key=f"{key}_exec", label_visibility="collapsed")

    if q:
        text = (df["lead_im"] + " " + df["title"].fillna("") + " " + df["summary"].fillna("") + " "
                + df["source"].fillna(""))
        df = df[text.str.contains(q, case=False, regex=False)]
    if "Novas hoje" in destaques:
        df = df[df["collected_day"] == config.today().isoformat()]
    if "Alta prioridade" in destaques:
        df = df[df["potential"].isin(["Muito Alto", "Alto"])]
    if verts:
        df = df[df["vertical"].isin(verts)]
    if pots:
        df = df[df["potential"].isin(pots)]
    if prazos:
        df = df[df["prazo"].map(prazo_tier).isin(prazos)]
    if sel_cats:
        df = df[df["category"].isin(sel_cats)]
    if sel_ufs:
        # astype(bool): com df vazio, apply devolve uma série "object" e o pandas a trataria como lista de
        # colunas (resultado sem colunas → KeyError 'potential' adiante); como bool, é sempre um filtro.
        df = df[df["uf_list"].apply(lambda lst: any(u in lst for u in sel_ufs)).astype(bool)]
    if fase != "Todas as fases":
        df = df[df["fase"] == fase]
    if executor != "Todas as situações":
        df = df[df["executor"] == executor]

    c5.download_button(
        "Baixar Excel organizado",
        data=lambda d=df: export.workbook_bytes(list(zip(d.to_dict("records"), d["ficha"])), load_accounts()),
        file_name=f"radar-cordeiro-{today_key}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key}_xlsx", disabled=df.empty, width="stretch", on_click="ignore",
    )
    html('<hr class="rc-sep">')
    return df



@st.dialog("Fontes de dados", width="large")
def sources_dialog() -> None:
    """Lista dos portais de onde vieram as notícias do painel (sem detalhes de como foram buscadas)."""
    from urllib.parse import urlsplit

    if not len(news):
        st.caption("Nenhuma notícia no painel ainda.")
        return
    sites = (news.assign(site=news["url"].map(lambda u: "{0.scheme}://{0.netloc}".format(urlsplit(u or ""))))
             .groupby("source").agg(n=("id", "count"), site=("site", "first"))
             .sort_values(["n"], ascending=False).reset_index())
    st.caption(f"{len(sites)} portais com notícias no painel ({len(news)} notícias).")
    rows = "".join(
        f'<a class="rc-src" href="{ui.h(r.site)}" target="_blank" rel="noopener">'
        f'<span>{ui.h(r.source)}</span><small>{r.n} notícia{"s" if r.n > 1 else ""}</small></a>'
        for r in sites.itertuples())
    html('<style>.rc-src{display:flex;justify-content:space-between;align-items:center;gap:12px;'
         'background:#e3e8e6;border-radius:8px;padding:8px 12px;margin:0 0 6px;color:#1f5c52!important;'
         'font-weight:600;text-decoration:none!important}.rc-src:hover{background:#d3dcd9}'
         '.rc-src small{color:#6b7a76;font-weight:400;white-space:nowrap;text-decoration:none!important}</style>' + rows)


# ------------------------------------------------------------------ cabeçalho
all_news = load_news()
# Notícias sem relação com a Cordeiro (demanda "Não") ficam fora das telas; o Histórico do admin pode mostrá-las.
news = all_news[all_news["relevante"] & ~all_news["repetida"]]
n_sem_relacao = int((~all_news["relevante"]).sum()) if len(all_news) else 0
n_repetidas = int((all_news["relevante"] & all_news["repetida"]).sum()) if len(all_news) else 0
runs = load_runs()
today_key = config.today().isoformat()
cfg = config.load_config()
exa_limit = cfg["exa"]["limite_diario"]
exa_today = db.exa_used(today_key)
fc_limit = int(cfg["firecrawl"].get("limite_diario", 10))
fc_today = db.api_used("firecrawl", today_key)
finished = runs[runs["finished_at"].notna()]
last_update = ui.fmt_date(finished.iloc[0]["finished_at"], with_time=True) if len(finished) else "—"

is_admin = auth.is_admin()
stats = [
    (f"{len(news)}", "Monitorados", False),
    (f"{int(news['potential'].isin(['Muito Alto', 'Alto']).sum())}", "Alta prioridade", False),
    (f"{int((news['collected_day'] == today_key).sum())}", "Novos hoje", False),
]
if is_admin:  # uso da cota do Exa: só na visão de administrador
    stats.append((f"{exa_today}/{exa_limit}", "Buscas Exa hoje", True))
    stats.append((f"{fc_today['used']}/{fc_limit}", "Buscas Firecrawl hoje", True))
stats.append((last_update, "Última atualização", False))
html(ui.header(stats))
c_tv, c_src, _, c_admin = st.columns([3, 2, 3, 2], vertical_alignment="center")
c_tv.page_link("pages/tv.py", label="Abrir Modo TV (carrossel para a TV)", icon="📺")
if c_src.button("🔍 Fontes de dados", key="open_sources", width="stretch"):
    sources_dialog()
with c_admin:
    auth.login_widget()
html(ui.about(news["source"].value_counts().head(12).index.tolist() if len(news) else []))
st.write("")

# Executivos veem só a Visão do dia; Histórico, Coleta e logs e Configuração são da visão de administrador.
if is_admin:
    tab_day, tab_hist, tab_run, tab_cfg = st.tabs(["Visão do dia", "Histórico", "Coleta e logs", "Configuração"])
else:
    tab_day = st.container()

# ------------------------------------------------------------------ visão do dia
with tab_day:
    if news.empty:
        html(ui.empty("Nenhuma notícia na base ainda. Execute a primeira coleta na aba “Coleta e logs”."))
    else:
        # "Mais antigas" = notícias já enviadas em newsletter; as outras duas opções mostram a última coleta.
        current = news[~news["antiga"]]
        days = sorted(current["collected_day"].unique(), reverse=True) or [today_key]
        day = today_key if today_key in days else days[0]
        label = "hoje" if day == today_key else "última coleta com resultados"
        c_cap, c_ord = st.columns([4, 1], vertical_alignment="center")
        order = c_ord.selectbox("Ordenar", ["Mais recentes", "Maior potencial", "Mais antigas"],
                                key="day_order", label_visibility="collapsed")
        if order == "Mais antigas":
            c_cap.caption(f"Notícias já enviadas na newsletter ({int(news['antiga'].sum())}), agrupadas por tema, "
                          "das mais antigas para as mais novas.")
            base = news[news["antiga"]]
        else:
            c_cap.caption(f"Notícias coletadas em **{ui.fmt_date(day)}** ({label}), agrupadas por tema e ordenadas por "
                          f"{'data' if order == 'Mais recentes' else 'potencial'}.")
            base = current[current["collected_day"] == day]
        df_day = newsletter_filters(base, "day")
        n_low = int((df_day["potential"] == "Baixo").sum())
        if n_low and st.toggle(f"Ocultar potencial Baixo ({n_low})", value=True, key="day_hide_low"):
            df_day = df_day[df_day["potential"] != "Baixo"]
        if order == "Maior potencial":
            df_day = df_day.sort_values(["pot_rank", "sort_date"], ascending=[True, False])
        else:
            df_day = df_day.sort_values("sort_date", ascending=order == "Mais antigas")
        if df_day.empty:
            html(ui.empty("Nenhuma notícia para os filtros escolhidos."))
        ordered = CATEGORIES + sorted(set(df_day["category"].dropna()) - set(CATEGORIES))
        for cat in ordered:
            group = df_day[df_day["category"] == cat]
            if group.empty:
                continue
            html(ui.section_title(cat, len(group), ui.CAT_COLORS.get(cat)))
            # Página leve: as principais de cada tema (já ordenadas por potencial) e o resto sob demanda.
            show_all = st.session_state.get(f"day_all_{cat}", False)
            render_cards(group if show_all else group.head(DAY_LIMIT), new_day=day, key="day")
            if len(group) > DAY_LIMIT:
                label = "Mostrar menos" if show_all else f"Mostrar todas as {len(group)} notícias de {cat}"
                st.button(label, key=f"day_more_{cat}", type="tertiary",
                          on_click=lambda k=f"day_all_{cat}": st.session_state.update({k: not st.session_state.get(k, False)}))

if not is_admin:  # visão do executivo termina aqui
    html(ui.footer(f"Última atualização: {last_update} · Fuso {config.TZ.key}"))
    st.stop()

# ------------------------------------------------------------------ histórico
with tab_hist:
    if news.empty:
        html(ui.empty("O histórico aparece depois da primeira coleta."))
    else:
        c1, c2, c3 = st.columns([1.2, 2, 1])
        date_field = c1.radio("Filtrar por data de", ["Coleta", "Publicação"], horizontal=True)
        col = "collected_day" if date_field == "Coleta" else "published_at"
        min_day = date.fromisoformat(news["collected_day"].min())
        period = c2.date_input("Período", (max(min_day, config.today() - timedelta(days=30)), config.today()),
                               format="DD/MM/YYYY")
        view = c3.segmented_control("Exibir", ["Cards", "Tabela"], default="Cards")

        c4, c5, c6, c7 = st.columns(4)
        fontes = c4.multiselect("Fonte", sorted(news["source"].dropna().unique()))
        motores = c5.multiselect("Mecanismo", sorted(news["engine"].dropna().unique()),
                                 format_func=lambda e: ui.ENGINE_LABEL.get(e, e))
        entradas = c6.multiselect("Entrada da Cordeiro", ["Prospectar", "Ampliar conta", "Preparar", "Monitorar"])
        origens = c7.multiselect("Ficha do executivo", ["newsletter", "automatica"],
                                 format_func={"newsletter": "Pesquisada", "automatica": "Preliminar"}.get)

        mostrar_irrelevantes = st.toggle(
            f"Mostrar notícias sem relação com a Cordeiro ({n_sem_relacao})", value=False, key="hist_irrelevantes",
            help="Demanda de guindaste/área = Não. Ficam fora da Visão do dia e do Modo TV.")
        mostrar_repetidas = st.toggle(
            f"Mostrar notícias repetidas ({n_repetidas})", value=False, key="hist_repetidas",
            help="A mesma matéria publicada por outros sites. Aparece só uma vez na Visão do dia e no Modo TV.")
        base = all_news
        if not mostrar_irrelevantes:
            base = base[base["relevante"]]
        if not mostrar_repetidas:
            base = base[~base["repetida"]]
        if isinstance(period, (tuple, list)) and len(period) == 2:
            start, end = (d.isoformat() for d in period)
            dates = base[col].fillna("").str[:10]
            base = base[(dates >= start) & (dates <= end)]
        if fontes:
            base = base[base["source"].isin(fontes)]
        if motores:
            base = base[base["engine"].isin(motores)]
        if entradas:
            base = base[base["entrada"].isin(entradas)]
        if origens:
            base = base[base["ficha_origem"].isin(origens)]
        df = newsletter_filters(base, "hist")

        sort = st.selectbox("Ordenar", ["Mais recentes", "Maior potencial", "Mais antigas"], label_visibility="collapsed")
        if sort == "Maior potencial":
            df = df.sort_values(["pot_rank", "sort_date"], ascending=[True, False])
        else:
            df = df.sort_values("sort_date", ascending=(sort == "Mais antigas"))

        html(ui.section_title("Todas as oportunidades", len(df)))
        table = df[["lead_im", "collected_at", "published_at", "category", "vertical", "ufs", "potential", "demand", "prazo",
                     "title", "summary", "source", "url", "term", "engine", "signal_type", "impacto", "times_seen",
                     "entrada", "fase", "executor", "ficha_origem"]]
        d1, d2, _ = st.columns([1, 1, 3])
        # Arquivos gerados no clique (data=callable): um link pré-gerado some quando o app reinicia/reconecta
        # e o clique dava "Download Button source error - 404".
        sep = "\n\n" + "=" * 80 + "\n\n"
        d1.download_button("Baixar CSV filtrado", data=lambda t=table: t.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"radar-cordeiro-{today_key}.csv", mime="text/csv",
                           on_click="ignore", key="hist_csv")
        d2.download_button("Baixar fichas do executivo (TXT)",
                           data=lambda f=df["ficha_texto"]: sep.join(f).encode("utf-8-sig"),
                           file_name=f"radar-cordeiro-fichas-{today_key}.txt", mime="text/plain",
                           on_click="ignore", key="hist_txt")
        if df.empty:
            html(ui.empty("Nenhuma notícia para os filtros escolhidos."))
        elif view == "Tabela":
            st.dataframe(
                table, hide_index=True, width="stretch",
                column_config={
                    "url": st.column_config.LinkColumn("URL"), "lead_im": "Lead IM",
                    "collected_at": "Coleta", "published_at": "Publicação", "category": "Tema",
                    "potential": "Potencial", "title": "Título", "source": "Fonte", "term": "Termo",
                    "engine": "Mecanismo", "times_seen": "Vezes vista", "entrada": "Entrada da Cordeiro",
                    "fase": "Fase", "executor": "Executor", "ficha_origem": "Ficha",
                },
            )
        else:
            page_size = 60
            pages = max(1, -(-len(df) // page_size))
            page = st.number_input(f"Página (de {pages})", 1, pages, 1) if pages > 1 else 1
            render_cards(df.iloc[(page - 1) * page_size: page * page_size], new_day=today_key, key="hist")

# ------------------------------------------------------------------ coleta e logs
with tab_run:
    c1, c2 = st.columns([1, 2])
    with c1:
        html(ui.exa_meter(exa_today, exa_limit))
        st.write("")
        html(ui.exa_meter(fc_today["used"], fc_limit, "Buscas Firecrawl hoje",
                          f"{fc_today['credits']} créditos usados hoje."))
    with c2:
        running = db.active_run()
        st.markdown("**Coleta manual**")
        st.caption("Executa Exa e Firecrawl (até o limite diário de cada um) e DuckDuckGo para todos os termos ativos. "
                   "Pode levar alguns minutos.")
        if not config.exa_api_key():
            st.warning("EXA_API_KEY não encontrada (.env ou Secrets do Streamlit Cloud) — buscas Exa ignoradas.")
        if not config.firecrawl_api_key():
            st.warning("FIRECRAWL_API_KEY não encontrada (.env ou Secrets do Streamlit Cloud) — buscas Firecrawl ignoradas.")
        if running:
            st.info(f"Coleta #{running['id']} em andamento desde {ui.fmt_date(running['started_at'], True)}.")
        if st.button("Executar coleta agora", type="primary", disabled=bool(running)):
            bar = st.progress(0.0, text="Iniciando…")
            result = run_collection(
                "manual", progress=lambda frac, msg: bar.progress(min(frac, 1.0), text=msg))
            st.session_state["last_result"] = result
            refresh()
            st.rerun()
        if res := st.session_state.pop("last_result", None):
            kind = {"ok": st.success, "com_erros": st.warning, "ignorada": st.info}.get(res["status"], st.error)
            kind(f"Coleta {res['status']}: {res['message']} Exa usado nesta execução: {res.get('exa_used', 0)}.")

        st.markdown("**Incluir notícia por link**")
        st.caption("Cole o link de uma matéria (ex.: recebida por WhatsApp). O painel lê título, resumo e data "
                   "da página, classifica e baixa as imagens.")
        with st.form("add_link", clear_on_submit=True, border=False):
            c_url, c_btn = st.columns([5, 1], vertical_alignment="bottom")
            link = c_url.text_input("Link da notícia", placeholder="https://…", label_visibility="collapsed")
            enviar = c_btn.form_submit_button("Incluir", type="primary", width="stretch")
        if enviar and link.strip():
            with st.spinner("Lendo a página e classificando…"):
                res = add_from_url(link.strip())
            if not res["ok"]:
                st.error(res["message"])
            elif not res["nova"]:
                st.info(res["message"])
            else:
                refresh()
                visivel = "" if res["demand"] != "Não" else " Ela ficou como sem relação com a Cordeiro (oculta)."
                st.success(f"{res['message']} — potencial {res['potential']}, demanda {res['demand']}, "
                           f"{res['images']} imagem(ns).{visivel}")

        n_sem_img = int((news["images"].str.len() == 0).sum()) if len(news) else 0
        if st.button(f"Buscar imagens que faltam ({n_sem_img} notícias sem imagem)", disabled=not n_sem_img):
            with st.spinner("Baixando imagens (até 2 por notícia)…"):
                images.backfill()
            refresh()
            st.rerun()

    st.markdown("#### Execuções")
    if runs.empty:
        st.caption("Nenhuma execução registrada.")
    else:
        st.dataframe(
            runs[["id", "trigger", "status", "started_at", "finished_at", "n_searches", "n_results", "n_new",
                  "exa_used", "firecrawl_used", "n_errors", "message"]],
            hide_index=True, width="stretch",
            column_config={"id": "#", "trigger": "Origem", "status": "Status", "started_at": "Início", "finished_at": "Fim",
                           "n_searches": "Buscas", "n_results": "Resultados", "n_new": "Novas",
                           "exa_used": "Exa", "firecrawl_used": "Firecrawl", "n_errors": "Erros", "message": "Resumo"},
        )
        run_id = st.selectbox("Detalhar buscas da execução", runs["id"].tolist())
        searches = db.read_sql(
            "SELECT engine, theme, term, n_results, n_new, status, error, executed_at FROM searches "
            "WHERE run_id=? ORDER BY id", (int(run_id),))
        st.dataframe(searches, hide_index=True, width="stretch",
                     column_config={"engine": "Mecanismo", "theme": "Tema", "term": "Termo", "n_results": "Resultados",
                                    "n_new": "Novas", "status": "Status", "error": "Erro", "executed_at": "Quando"})

    st.markdown("#### Log de erros")
    errors = db.read_sql("SELECT id, run_id, occurred_at, engine, term, message, details FROM errors "
                         "ORDER BY id DESC LIMIT 200")
    if errors.empty:
        st.caption("Nenhum erro registrado. 🎉")
    else:
        st.dataframe(errors.drop(columns=["details"]), hide_index=True, width="stretch",
                     column_config={"run_id": "Execução", "occurred_at": "Quando", "engine": "Mecanismo",
                                    "term": "Termo", "message": "Erro"})
        with st.expander("Detalhes técnicos (traceback) do erro mais recente"):
            st.code(errors.iloc[0]["details"] or "—", language="text")

# ------------------------------------------------------------------ configuração
with tab_cfg:
    st.caption(f"Arquivo: `{config.TERMS_PATH}`. Alterações aqui sobrescrevem o arquivo (comentários são perdidos).")
    terms_df = pd.DataFrame(list(config.iter_terms(cfg, only_active=False)),
                            columns=["tema", "texto", "exa", "firecrawl", "prioridade", "ativo"])
    theme_opts = list(dict.fromkeys(CATEGORIES + terms_df["tema"].tolist()))
    edited = st.data_editor(
        terms_df, num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "tema": st.column_config.SelectboxColumn("Tema", options=theme_opts, required=True),
            "texto": st.column_config.TextColumn("Termo de busca", required=True, width="large"),
            "exa": st.column_config.CheckboxColumn("Usar no Exa", default=False),
            "firecrawl": st.column_config.CheckboxColumn("Usar no Firecrawl", default=False,
                                                         help="Sem nenhum marcado, usa todos por prioridade (rodízio)"),
            "prioridade": st.column_config.NumberColumn("Prioridade", min_value=1, max_value=5, step=1, default=3),
            "ativo": st.column_config.CheckboxColumn("Ativo", default=True),
        },
        key="terms_editor",
    )
    n_exa = int(edited[edited["ativo"].fillna(True)]["exa"].fillna(False).sum())
    if n_exa > exa_limit:
        st.info(f"{n_exa} termos marcados para o Exa e limite de {exa_limit}/dia: haverá rodízio diário pela prioridade.")

    c1, c2, c3 = st.columns(3)
    periodo = c1.selectbox("Período DuckDuckGo", ["d", "w", "m"], index=["d", "w", "m"].index(cfg["ddg"].get("periodo", "w")),
                           format_func={"d": "Último dia", "w": "Última semana", "m": "Último mês"}.get)
    ddg_n = c1.number_input("Resultados por busca (DuckDuckGo)", 5, 50, int(cfg["ddg"].get("resultados_por_busca", 15)))
    exa_lim = c2.number_input("Limite diário Exa (máx. 5)", 0, config.EXA_HARD_LIMIT, int(exa_limit))
    exa_n = c2.number_input("Resultados por busca (Exa)", 1, 25, int(cfg["exa"].get("resultados_por_busca", 10)))
    exa_days = c3.number_input("Exa: publicado nos últimos N dias", 1, 60, int(cfg["exa"].get("dias_retroativos", 7)))
    excl = c3.text_area("Excluir notícias que contenham (uma por linha)", "\n".join(cfg.get("excluir_se_contiver", [])))

    f1, f2, f3, f4 = st.columns(4)
    fc_on = f1.toggle("Firecrawl ativo", value=bool(cfg["firecrawl"].get("ativo", True)))
    fc_lim = f2.number_input("Limite diário Firecrawl (buscas)", 0, 200, fc_limit,
                             help="Cada busca consome créditos (~2 por 10 notícias).")
    fc_n = f3.number_input("Resultados por busca (Firecrawl)", 1, 50, int(cfg["firecrawl"].get("resultados_por_busca", 10)))
    fc_per = f4.selectbox("Período Firecrawl", ["d", "w", "m"],
                          index=["d", "w", "m"].index(cfg["firecrawl"].get("periodo", "w")),
                          format_func={"d": "Último dia", "w": "Última semana", "m": "Último mês"}.get)

    if st.button("Salvar configuração", type="primary"):
        rows = edited.dropna(subset=["texto"])
        rows = rows[rows["texto"].astype(str).str.strip() != ""]
        temas = []
        for tema in dict.fromkeys(rows["tema"].fillna("Geral")):
            termos = [{"texto": str(r.texto).strip(), "exa": bool(r.exa),
                       "firecrawl": bool(r.firecrawl) if pd.notna(r.firecrawl) else False, "prioridade": int(r.prioridade) if pd.notna(r.prioridade) else 3,
                       "ativo": bool(r.ativo if pd.notna(r.ativo) else True)}
                      for r in rows[rows["tema"].fillna("Geral") == tema].itertuples()]
            temas.append({"nome": tema, "termos": termos})
        cfg["temas"] = temas
        cfg["ddg"].update({"periodo": periodo, "resultados_por_busca": int(ddg_n)})
        cfg["exa"].update({"limite_diario": int(exa_lim), "resultados_por_busca": int(exa_n),
                           "dias_retroativos": int(exa_days)})
        cfg["firecrawl"].update({"ativo": bool(fc_on), "limite_diario": int(fc_lim),
                                 "resultados_por_busca": int(fc_n), "periodo": fc_per})
        cfg["excluir_se_contiver"] = [w.strip() for w in excl.splitlines() if w.strip()]
        config.save_config(cfg)
        st.success(f"Configuração salva: {len(rows)} termos em {len(temas)} temas.")

    st.markdown("#### Fichas do executivo pesquisadas")
    st.caption("Importe o HTML da newsletter (versão integrada) para trazer as notícias com a Ficha do executivo "
               "pesquisada, os contatos e os canais de cadastro. A classificação do analista prevalece sobre a "
               "automática. Notícias sem ficha pesquisada exibem uma ficha preliminar com o roteiro padrão.")
    n_fichas = int((news["ficha_origem"] == "newsletter").sum()) if len(news) else 0
    st.caption(f"Na base hoje: **{n_fichas}** fichas pesquisadas e **{len(load_accounts())}** contas com canal oficial.")
    upload = st.file_uploader("HTML da newsletter", type=["html", "htm"])
    as_old = st.checkbox("Newsletter já enviada: colocar as notícias em “Mais antigas”", value=True)
    if upload is not None and st.button("Importar fichas"):
        try:
            result = dossier.import_newsletter(upload.getvalue().decode("utf-8"), antigas=as_old)
        except ValueError as exc:
            st.error(str(exc))
        else:
            # As notícias importadas não passam pela coleta: busca as imagens delas agora.
            with st.spinner("Buscando imagens das notícias importadas…"):
                n_img = images.backfill()
            refresh()
            st.success(f"Importado: {result['fichas']} fichas, {result['noticias_novas']} notícias novas, "
                       f"{result['noticias_atualizadas']} já existentes atualizadas, {result['contas']} contas; "
                       f"{n_img} imagens.")

html(ui.footer(f"Última atualização: {last_update} · Fuso {config.TZ.key}"))
