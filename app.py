"""Painel Streamlit do Radar Cordeiro. Lê o SQLite alimentado pelo scheduler.

    streamlit run app.py
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from radar import config, db, dossier, export, images, ui
from radar.collector import run_collection
from radar.classify import CATEGORIES

st.set_page_config(page_title="Radar Cordeiro", page_icon="📡", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)
db.init_db()

POT_RANK = {p: i for i, p in enumerate(ui.POTENTIALS)}


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


@st.cache_data(ttl=60, show_spinner=False)
def load_news() -> pd.DataFrame:
    df = db.read_sql("SELECT * FROM news ORDER BY collected_at DESC")
    df["pot_rank"] = df["potential"].map(POT_RANK).fillna(9)
    df["sort_date"] = df["published_at"].fillna(df["collected_at"])
    df["uf_list"] = df["ufs"].fillna("").str.split(",")
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
def load_runs(limit: int = 50) -> pd.DataFrame:
    return db.read_sql("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))


def refresh() -> None:
    load_news.clear()
    load_runs.clear()
    load_accounts.clear()


def render_cards(df: pd.DataFrame, new_day: str | None = None, limit: int | None = None) -> None:
    rows = df.head(limit) if limit else df
    accounts = load_accounts()
    cards = [
        ui.card(r, is_new=(new_day is not None and r["collected_day"] == new_day),
                ficha_html=ui.ficha(r, r["ficha"], accounts, r["ficha_texto"]), images=r["images"])
        for r in rows.to_dict("records")
    ]
    html(ui.grid(cards))


VERTICALS = ["Energia", "Minerais", "Infraestrutura"]
PRAZOS = ["Curto", "Médio", "Longo", "A confirmar"]
UF_PRIORITY = ["CE", "PA", "NE", "BR"]
FILTER_SUFFIXES = ("q", "v", "p", "pz", "c", "uf", "fase", "exec")


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
    q = c_q.text_input("Buscar", placeholder="Buscar por palavra-chave, empresa, projeto…", key=f"{key}_q",
                       label_visibility="collapsed")
    c_clear.button("Limpar filtros", key=f"{key}_clear", on_click=clear_filters, args=(key,), type="tertiary")

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
        text = df["title"].fillna("") + " " + df["summary"].fillna("") + " " + df["source"].fillna("")
        df = df[text.str.contains(q, case=False, regex=False)]
    if verts:
        df = df[df["vertical"].isin(verts)]
    if pots:
        df = df[df["potential"].isin(pots)]
    if prazos:
        df = df[df["prazo"].map(prazo_tier).isin(prazos)]
    if sel_cats:
        df = df[df["category"].isin(sel_cats)]
    if sel_ufs:
        df = df[df["uf_list"].apply(lambda lst: any(u in lst for u in sel_ufs))]
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


# ------------------------------------------------------------------ cabeçalho
news = load_news()
runs = load_runs()
today_key = config.today().isoformat()
cfg = config.load_config()
exa_limit = cfg["exa"]["limite_diario"]
exa_today = db.exa_used(today_key)
finished = runs[runs["finished_at"].notna()]
last_update = ui.fmt_date(finished.iloc[0]["finished_at"], with_time=True) if len(finished) else "—"

html(ui.header([
    (f"{len(news)}", "Monitorados", False),
    (f"{int(news['potential'].isin(['Muito Alto', 'Alto']).sum())}", "Alta prioridade", False),
    (f"{int((news['collected_day'] == today_key).sum())}", "Novos hoje", False),
    (f"{exa_today}/{exa_limit}", "Buscas Exa hoje", True),
    (last_update, "Última atualização", False),
]))
st.page_link("pages/tv.py", label="Abrir Modo TV (carrossel para a TV)", icon="📺")
html(ui.about(news["source"].value_counts().head(12).index.tolist() if len(news) else []))
st.write("")

tab_day, tab_hist, tab_run, tab_cfg = st.tabs(["Visão do dia", "Histórico", "Coleta e logs", "Configuração"])

# ------------------------------------------------------------------ visão do dia
with tab_day:
    if news.empty:
        html(ui.empty("Nenhuma notícia na base ainda. Execute a primeira coleta na aba “Coleta e logs”."))
    else:
        days = sorted(news["collected_day"].unique(), reverse=True)
        day = today_key if today_key in days else days[0]
        label = "hoje" if day == today_key else "última coleta com resultados"
        st.caption(f"Notícias coletadas em **{ui.fmt_date(day)}** ({label}), agrupadas por tema e ordenadas por potencial.")
        df_day = newsletter_filters(news[news["collected_day"] == day], "day")
        n_low = int((df_day["potential"] == "Baixo").sum())
        if n_low and st.toggle(f"Ocultar potencial Baixo ({n_low})", value=True, key="day_hide_low"):
            df_day = df_day[df_day["potential"] != "Baixo"]
        df_day = df_day.sort_values(["pot_rank", "sort_date"], ascending=[True, False])
        if df_day.empty:
            html(ui.empty("Nenhuma notícia para os filtros escolhidos."))
        ordered = CATEGORIES + sorted(set(df_day["category"].dropna()) - set(CATEGORIES))
        for cat in ordered:
            group = df_day[df_day["category"] == cat]
            if group.empty:
                continue
            html(ui.section_title(cat, len(group), ui.CAT_COLORS.get(cat)))
            render_cards(group, new_day=day)

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

        base = news
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
        table = df[["collected_at", "published_at", "category", "vertical", "ufs", "potential", "demand", "prazo",
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
                    "url": st.column_config.LinkColumn("URL"),
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
            render_cards(df.iloc[(page - 1) * page_size: page * page_size], new_day=today_key)

# ------------------------------------------------------------------ coleta e logs
with tab_run:
    c1, c2 = st.columns([1, 2])
    with c1:
        html(ui.exa_meter(exa_today, exa_limit))
    with c2:
        running = db.active_run()
        st.markdown("**Coleta manual**")
        st.caption("Executa Exa (apenas se ainda houver cota no dia) e DuckDuckGo para todos os termos ativos. "
                   "Pode levar alguns minutos.")
        if not config.exa_api_key():
            st.warning("EXA_API_KEY não encontrada (.env ou Secrets do Streamlit Cloud) — a coleta usará apenas o DuckDuckGo.")
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
                  "exa_used", "n_errors", "message"]],
            hide_index=True, width="stretch",
            column_config={"id": "#", "trigger": "Origem", "status": "Status", "started_at": "Início", "finished_at": "Fim",
                           "n_searches": "Buscas", "n_results": "Resultados", "n_new": "Novas",
                           "exa_used": "Exa", "n_errors": "Erros", "message": "Resumo"},
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
                            columns=["tema", "texto", "exa", "prioridade", "ativo"])
    theme_opts = list(dict.fromkeys(CATEGORIES + terms_df["tema"].tolist()))
    edited = st.data_editor(
        terms_df, num_rows="dynamic", hide_index=True, width="stretch",
        column_config={
            "tema": st.column_config.SelectboxColumn("Tema", options=theme_opts, required=True),
            "texto": st.column_config.TextColumn("Termo de busca", required=True, width="large"),
            "exa": st.column_config.CheckboxColumn("Usar no Exa", default=False),
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

    if st.button("Salvar configuração", type="primary"):
        rows = edited.dropna(subset=["texto"])
        rows = rows[rows["texto"].astype(str).str.strip() != ""]
        temas = []
        for tema in dict.fromkeys(rows["tema"].fillna("Geral")):
            termos = [{"texto": str(r.texto).strip(), "exa": bool(r.exa), "prioridade": int(r.prioridade) if pd.notna(r.prioridade) else 3,
                       "ativo": bool(r.ativo if pd.notna(r.ativo) else True)}
                      for r in rows[rows["tema"].fillna("Geral") == tema].itertuples()]
            temas.append({"nome": tema, "termos": termos})
        cfg["temas"] = temas
        cfg["ddg"].update({"periodo": periodo, "resultados_por_busca": int(ddg_n)})
        cfg["exa"].update({"limite_diario": int(exa_lim), "resultados_por_busca": int(exa_n),
                           "dias_retroativos": int(exa_days)})
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
    if upload is not None and st.button("Importar fichas"):
        try:
            result = dossier.import_newsletter(upload.getvalue().decode("utf-8"))
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
