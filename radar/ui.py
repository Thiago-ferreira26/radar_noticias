"""Identidade visual da newsletter Radar Cordeiro aplicada ao Streamlit (CSS + blocos HTML)."""
from __future__ import annotations

import re
from datetime import datetime
from html import escape

from .dossier import DOCS_TO_PREPARE

CAT_COLORS = {
    "Energia": "#2f7fa8", "Portos": "#3f63ab", "Mineração": "#a8752f", "Industrial": "#7160a8",
    "Logística/Hidrovias": "#3f8f6d", "Saneamento": "#3f9c9c", "Óleo & Gás": "#8a5a44",
    "Infraestrutura": "#4a6a86",
}
VERT_COLORS = {"Energia": "#2f7fa8", "Minerais": "#a8752f", "Infraestrutura": "#4a6a86"}
POTENTIALS = ["Muito Alto", "Alto", "Médio", "Baixo"]
POT_CLASS = {"Muito Alto": "pot-muito-alto", "Alto": "pot-alto", "Médio": "pot-medio", "Baixo": "pot-baixo"}
ENGINE_LABEL = {"exa": "Exa", "duckduckgo": "DuckDuckGo", "newsletter": "Newsletter"}
UF_LABEL = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins", "NE": "Nordeste (regional)", "BR": "Nacional",
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Sans+Condensed:wght@600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
:root{
  --bg:#eef1f0; --surface:#ffffff; --surface-alt:#e2e8e5; --ink:#16211f; --ink-soft:#51615c; --ink-faint:#7c8b86;
  --border:#d5dcd8; --teal:#1f5f5a; --teal-deep:#0d2b2a; --teal-tint:#e0ecea; --amber:#c9761a; --amber-deep:#a34a12;
  --amber-tint:#f7e6cf; --terracotta:#a1441f; --neutral-tag:#7c8b86;
  --shadow:0 1px 2px rgba(13,43,42,.06), 0 8px 20px -12px rgba(13,43,42,.18);
}
html, body, .stApp, [data-testid="stAppViewContainer"]{background:var(--bg); font-family:"IBM Plex Sans", system-ui, sans-serif;}
[data-testid="stHeader"]{background:transparent;}
.block-container{max-width:1240px; padding-top:1.2rem;}
h1,h2,h3{font-family:"IBM Plex Sans Condensed", "IBM Plex Sans", sans-serif;}

/* Header */
.rc-top{background:var(--teal-deep); color:#eef4f2; border-radius:12px; padding:22px 22px 18px;
  border-bottom:3px solid var(--amber); display:flex; align-items:center; gap:18px; flex-wrap:wrap;
  justify-content:space-between; box-shadow:var(--shadow);}
.rc-brand{display:flex; align-items:center; gap:14px;}
.rc-mark{width:40px; height:40px; border-radius:50%; flex:none; border:1px solid rgba(238,244,242,.35);
  background:radial-gradient(circle at 50% 50%, transparent 0 3px, rgba(238,244,242,.18) 3px 4px, transparent 4px 9px,
  rgba(238,244,242,.18) 9px 10px, transparent 10px 15px, rgba(238,244,242,.18) 15px 16px, transparent 16px 19px),
  conic-gradient(from 0deg, var(--amber) 0deg, transparent 55deg 360deg), var(--teal-deep);
  animation:rc-sweep 4s linear infinite;}
@keyframes rc-sweep{to{transform:rotate(360deg);}}
@media (prefers-reduced-motion: reduce){.rc-mark{animation:none;}}
.rc-brand h1{font-family:"IBM Plex Sans Condensed"; font-weight:700; font-size:26px; margin:0; padding:0;
  text-transform:uppercase; letter-spacing:.01em; color:#eef4f2;}
.rc-brand p{margin:2px 0 0; font-size:13.5px; color:#b9cbc7;}
.rc-stats{display:flex; gap:10px; flex-wrap:wrap;}
.rc-stat{background:rgba(238,244,242,.06); border:1px solid rgba(238,244,242,.16); border-radius:10px;
  padding:8px 14px; min-width:112px;}
.rc-stat b{display:block; font-family:"IBM Plex Mono", monospace; font-size:20px; color:#fff; font-variant-numeric:tabular-nums;}
.rc-stat span{font-size:11.5px; color:#a9bfba; text-transform:uppercase; letter-spacing:.04em;}
.rc-stat.hl b{color:#eba14a;}

/* About */
.rc-about{margin-top:16px; background:var(--surface); border:1px solid var(--border); border-radius:12px;
  padding:16px 18px; box-shadow:var(--shadow); display:grid; grid-template-columns:1.3fr 1fr; gap:18px;}
@media (max-width:760px){.rc-about{grid-template-columns:1fr;}}
.rc-about h2{font-family:"IBM Plex Sans Condensed"; font-size:15px; text-transform:uppercase; letter-spacing:.04em;
  margin:0 0 6px; padding:0; color:var(--teal);}
.rc-about p{margin:0; font-size:13.5px; line-height:1.55; color:var(--ink-soft);}
.rc-chips{display:flex; flex-wrap:wrap; gap:6px;}
.rc-chip{font-size:12px; padding:4px 9px; border-radius:999px; background:var(--surface-alt); color:var(--ink-soft);
  border:1px solid var(--border); font-family:"IBM Plex Mono", monospace;}

/* Sections */
.rc-section{font-family:"IBM Plex Sans Condensed"; text-transform:uppercase; letter-spacing:.04em; font-size:16px;
  font-weight:700; margin:26px 0 12px; color:var(--ink); display:flex; align-items:center; gap:8px;}
.rc-section .dot{width:10px; height:10px; border-radius:50%;}
.rc-section .count{font-family:"IBM Plex Mono"; font-size:12px; color:var(--ink-faint); font-weight:400;
  text-transform:none; letter-spacing:0;}
.rc-grid{display:grid; grid-template-columns:repeat(auto-fill, minmax(340px,1fr)); gap:14px;}
@media (max-width:420px){.rc-grid{grid-template-columns:1fr;}}

/* Card */
.rc-card{background:var(--surface); border:1px solid var(--border); border-radius:11px; padding:14px 15px 13px 14px;
  box-shadow:var(--shadow); border-left:5px solid var(--neutral-tag); display:flex; flex-direction:column; gap:8px;}
.rc-card.pot-muito-alto{border-left-color:var(--amber-deep);}
.rc-card.pot-alto{border-left-color:var(--amber);}
.rc-card.pot-medio{border-left-color:var(--terracotta);}
.rc-card.pot-baixo{border-left-color:var(--neutral-tag);}
.rc-img{width:100% !important; max-width:none !important; height:170px; object-fit:cover; border-radius:8px; background:var(--surface-alt); display:block;}
.rc-card-top{display:flex; justify-content:space-between; align-items:flex-start; gap:8px;}
.rc-tags{display:flex; gap:6px; flex-wrap:wrap; align-items:center;}
.rc-tag{font-size:10.8px; padding:2.5px 8px; border-radius:999px; font-weight:600; text-transform:uppercase;
  letter-spacing:.03em; white-space:nowrap;}
.rc-tag.cat{background:var(--surface-alt); color:var(--ink-soft); display:inline-flex; align-items:center; gap:5px;
  text-transform:none; font-weight:500;}
.rc-tag.cat .dot{width:7px; height:7px; border-radius:50%;}
.rc-tag.vert{background:transparent; border:1.5px solid currentColor; font-weight:700;}
.rc-tag.uf{background:var(--teal-tint); color:var(--teal); font-family:"IBM Plex Mono";}
.rc-tag.eng{background:var(--surface-alt); color:var(--ink-faint); font-family:"IBM Plex Mono"; text-transform:none;}
.rc-tag.pot{color:#fff;}
.rc-tag.pot.pot-muito-alto{background:var(--amber-deep);} .rc-tag.pot.pot-alto{background:var(--amber);}
.rc-tag.pot.pot-medio{background:var(--terracotta);} .rc-tag.pot.pot-baixo{background:var(--neutral-tag);}
.rc-new{font-size:10.5px; font-weight:700; color:var(--teal-deep); background:var(--amber); padding:2.5px 8px;
  border-radius:999px; text-transform:uppercase; letter-spacing:.03em; flex:none;}
.rc-card h3{margin:0; padding:0; font-family:"IBM Plex Sans"; font-size:15.5px; line-height:1.35; font-weight:600;}
.rc-card h3 a{color:var(--ink) !important; text-decoration:none;}
.rc-card h3 a:hover{color:var(--teal) !important; text-decoration:underline;}
.rc-card p.summary{margin:0; font-size:13px; line-height:1.5; color:var(--ink-soft);}
.rc-impact{background:var(--teal-deep); border-radius:9px; padding:10px 12px 11px;}
.rc-impact .head{font-family:"IBM Plex Sans Condensed"; font-size:11px; font-weight:700; text-transform:uppercase;
  letter-spacing:.05em; color:var(--amber); margin-bottom:5px;}
.rc-impact .demand{display:inline-block; font-size:11px; font-weight:600; color:#eef4f2; background:rgba(238,244,242,.1);
  border-radius:999px; padding:2px 9px; margin-bottom:6px;}
.rc-impact p{margin:0; font-size:12.5px; line-height:1.5; color:#d6e4e0;}
.rc-signal{font-size:11px; color:var(--ink-soft); font-style:italic;}
.rc-meta{display:flex; justify-content:space-between; align-items:center; gap:8px; margin-top:auto; padding-top:8px;
  border-top:1px dashed var(--border); font-size:11.5px; color:var(--ink-faint); font-family:"IBM Plex Mono";}
.rc-term{font-size:11px; color:var(--ink-faint);}
.rc-empty{padding:40px 20px; text-align:center; color:var(--ink-faint); font-size:14px; background:var(--surface);
  border:1px dashed var(--border); border-radius:12px;}

/* Ficha do executivo (mesmo desenho da newsletter) */
.cord-action{border:1px solid var(--border); border-radius:10px; overflow:hidden; background:var(--surface);}
.cord-summary{padding:13px; background:var(--teal-tint); color:var(--ink); font-size:13px; line-height:1.55;}
.cord-summary strong{display:block; color:var(--teal); font-size:14px;}
.cord-summary p{margin:5px 0; font-size:13px; line-height:1.55;}
.cord-status{font-size:11px; background:var(--surface); padding:3px 7px; border-radius:5px; display:inline-block;}
.cord-origin{font-size:10.5px; font-weight:700; text-transform:uppercase; letter-spacing:.03em; padding:2px 7px;
  border-radius:999px; margin-left:6px; vertical-align:middle;}
.cord-origin.newsletter{background:var(--teal); color:#fff;}
.cord-origin.automatica{background:var(--amber-tint); color:var(--amber-deep);}
.cord-action details{padding:0;}
.cord-action summary{cursor:pointer; color:var(--teal); font-weight:700; font-size:13px;}
.cord-dossier>summary{padding:14px;}
.cord-dossier-body{padding:0 12px 12px;}
.cord-topic{margin:7px 0; border:1px solid var(--border); border-radius:7px; overflow:hidden;}
.cord-topic>summary{padding:12px; background:#f3f6f5; font-size:13px; line-height:1.4;}
.cord-topic[open]>summary{background:var(--teal-tint); border-bottom:1px solid var(--border);}
.cord-topic-body{padding:4px 13px 12px;}
.cord-action h4{font-family:"IBM Plex Sans"; font-size:12px; margin:14px 0 6px; padding:0; text-transform:uppercase;
  letter-spacing:.4px; color:var(--teal); font-weight:700;}
.cord-action p, .cord-action li{font-size:13px; line-height:1.6; color:var(--ink);}
.cord-action p{margin:4px 0;}
.cord-action ol, .cord-action ul{padding-left:21px; margin:8px 0;}
.cord-action li{margin:6px 0;}
.cord-agenda-note{color:var(--ink-soft) !important;}
.cord-route-step{margin:10px 0; border:1px solid var(--border); border-radius:7px; overflow:hidden;}
.cord-route-step>summary{padding:12px; background:var(--teal-tint);}
.cord-route-step>div{padding:0 13px 10px;}
.cord-company{padding:10px 0; border-bottom:1px solid var(--border); font-size:13px;}
.cord-company:last-of-type{border-bottom:0;}
.cord-company b{display:block;}
.cord-company span{display:block; font-size:12px; color:var(--ink-soft);}
.cord-company p{overflow-wrap:anywhere;}
.cord-company small{font-size:11px; color:var(--ink-soft);}
.cord-register{background:var(--teal-tint); border-radius:7px; margin:10px 0; padding:0 10px 4px;}
.cord-register>summary{font-size:12px; padding:8px 0;}
.cord-template{border-left:3px solid var(--teal); padding:12px; background:var(--surface-alt);}
.cord-none{font-size:12px !important; padding:10px; background:var(--surface-alt); border-radius:6px;}
.cord-copy textarea{width:100%; min-height:220px; font-family:"IBM Plex Mono"; font-size:11.5px; border:1px solid var(--border);
  border-radius:6px; padding:8px; background:var(--surface); color:var(--ink); resize:vertical;}
.cord-copy small{display:block; color:var(--ink-faint); font-size:11px; margin-bottom:6px;}

/* Barra de filtros (chips da newsletter) */
.rc-chiprow-label{font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--ink-faint);}
.rc-sep{border:0; border-top:1px solid var(--border); margin:8px 0 10px;}
[data-testid="stButtonGroup"] button{border-radius:999px !important; border:1px solid var(--border) !important;
  background:var(--surface) !important; color:var(--ink-soft) !important; padding:6px 11px; min-height:0;}
[data-testid="stButtonGroup"] button:hover{border-color:var(--teal) !important;}
[data-testid="stButtonGroup"] button p{font-size:12.5px; font-family:"IBM Plex Sans";}
[data-testid="stButtonGroup"] button[aria-pressed="true"]{
  background:var(--teal) !important; border-color:var(--teal) !important; color:#fff !important;}
[data-testid="stButtonGroup"] button[aria-pressed="true"] p{
  font-weight:600; color:#fff;}
.rc-criteria{margin:-4px 0 6px;}
.rc-criteria summary{font-size:12px; color:var(--teal); cursor:pointer; font-weight:600; list-style:none;}
.rc-criteria summary::-webkit-details-marker{display:none;}
.rc-criteria summary::before{content:"▸ "; font-size:10px;}
.rc-criteria[open] summary::before{content:"▾ ";}
.rc-criteria-body{margin-top:8px; padding:12px 14px; background:var(--surface); border:1px solid var(--border);
  border-radius:10px; max-width:640px;}
.rc-criteria-body p{margin:0 0 6px; font-size:12.5px; color:var(--ink-soft);}
.rc-criteria-body ol{margin:0 0 6px; padding-left:18px;}
.rc-criteria-body li{font-size:12.5px; line-height:1.5; color:var(--ink-soft); margin:4px 0;}
.rc-criteria-body b{color:var(--ink);}

/* Exa meter */
.rc-meter{background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:14px 16px; box-shadow:var(--shadow);}
.rc-meter .lbl{font-family:"IBM Plex Sans Condensed"; text-transform:uppercase; letter-spacing:.04em; font-size:13px; color:var(--teal); font-weight:700;}
.rc-meter .val{font-family:"IBM Plex Mono"; font-size:26px; font-weight:600; color:var(--ink);}
.rc-meter .trk{height:10px; background:var(--surface-alt); border-radius:6px; overflow:hidden; margin-top:6px;}
.rc-meter .trk i{display:block; height:100%; background:var(--amber);}
.rc-meter small{color:var(--ink-faint); font-size:12px;}

.rc-foot{margin-top:34px; padding-top:16px; border-top:1px solid var(--border); font-size:12px; color:var(--ink-faint);
  display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px;}

/* Componentes Streamlit no tom da newsletter */
.stTabs [data-baseweb="tab-list"]{gap:4px;}
.stTabs [data-baseweb="tab"]{font-family:"IBM Plex Sans Condensed"; text-transform:uppercase; letter-spacing:.03em; font-weight:700;}
div.stButton > button[kind="primary"]{background:var(--amber); color:var(--teal-deep); border:none;
  font-family:"IBM Plex Sans Condensed"; font-weight:700; text-transform:uppercase; letter-spacing:.03em;}
div.stButton > button[kind="primary"]:hover{background:var(--amber-deep); color:#fff;}
</style>
"""


def h(text) -> str:
    # "$" escapado para o Markdown do Streamlit não interpretar "R$ ... R$" como fórmula LaTeX.
    # Quebras de linha viram entidade: uma linha em branco encerraria o bloco HTML no Markdown.
    return escape(str(text or ""), quote=True).replace("$", "&#36;").replace("\n", "&#10;")


def fmt_date(value, with_time: bool = False) -> str:
    if not value or str(value) in ("nan", "None", "NaT"):
        return "—"
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)[:10]
    return dt.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")


def header(stats: list[tuple[str, str, bool]]) -> str:
    cells = "".join(
        f'<div class="rc-stat{" hl" if hl else ""}"><b>{h(v)}</b><span>{h(lbl)}</span></div>' for v, lbl, hl in stats
    )
    return (
        '<div class="rc-top"><div class="rc-brand"><div class="rc-mark" aria-hidden="true"></div><div>'
        "<h1>Radar Cordeiro</h1>"
        "<p>Inteligência de Mercado — sinais de demanda para locação de guindastes e área</p>"
        f'</div></div><div class="rc-stats">{cells}</div></div>'
    )


def about(sources: list[str]) -> str:
    chips = "".join(f'<span class="rc-chip">{h(s)}</span>' for s in sources) or '<span class="rc-chip">—</span>'
    return (
        '<div class="rc-about"><div><h2>Como este painel funciona</h2>'
        "<p>Todo dia às 08:00 (horário de Fortaleza) uma rotina automática busca no Exa (até 5 buscas/dia) e no "
        "DuckDuckGo notícias do Brasil sobre investimentos, obras e projetos que possam gerar demanda de locação de "
        "guindaste e área — energia, portos, mineração, construção industrial e infraestrutura, com prioridade para "
        "Ceará e Pará. Cada item recebe, por regras automáticas, vertical, categoria, UF, prazo, potencial "
        "(Baixo a Muito Alto) e impacto provável para a Cordeiro; itens repetidos não são duplicados. "
        "A classificação é uma triagem — valide antes de prospectar.</p></div>"
        f'<div><h2>Fontes mais frequentes</h2><div class="rc-chips">{chips}</div></div></div>'
    )


def criteria() -> str:
    """Regras de potencial (mesmo texto da newsletter), recolhidas em "Como o potencial é calculado"."""
    return (
        '<details class="rc-criteria"><summary>Como o potencial é calculado</summary><div class="rc-criteria-body">'
        "<p>Aplicado em ordem — a primeira regra que se encaixa define o teto da nota:</p><ol>"
        "<li>Sem relação prática com içamento/movimentação de carga pesada (regulatório, discussão setorial, "
        "saneamento simples, conteúdo macro sem obra)? → <b>Baixo</b>, fim.</li>"
        "<li>É panorama agregado/nacional, sem projeto ou UF específica nomeada? → no máximo <b>Médio</b>.</li>"
        "<li>Fica fora da área de atuação conhecida da Cordeiro (não é CE, PA, nem um estado já mapeado/Nordeste)? "
        "→ no máximo <b>Médio</b>.</li>"
        "<li>Ainda depende de decisão futura — edital em consulta, decisão de investimento (FID) não definida, ou só "
        "estudo — sem ser investimento aprovado/contratado nem obra em andamento? → no máximo <b>Alto</b>.</li>"
        "<li>Passou por tudo acima: está em CE/PA, no segmento certo (energia, portos, mineração, industrial "
        "pesado), já é investimento aprovado/obra em andamento e tem porte financeiro relevante → <b>Muito Alto</b>. "
        "Mesmas condições fora de CE/PA (mas dentro da área de atuação) → <b>Alto</b>.</li>"
        "</ol><p>Nas notícias coletadas automaticamente, estas regras são aplicadas por palavras-chave "
        "(triagem); nas fichas pesquisadas vale a nota do analista.</p></div></details>"
    )


def section_title(title: str, count: int, color: str | None = None) -> str:
    dot = f'<span class="dot" style="background:{color}"></span>' if color else ""
    return f'<div class="rc-section">{dot}{h(title)} <span class="count">({count})</span></div>'


def _topic(title: str, body: str) -> str:
    return f'<details class="cord-topic"><summary>{title}</summary><div class="cord-topic-body">{body}</div></details>'


def _ol(items) -> str:
    return "<ol>" + "".join(f"<li>{h(t)}</li>" for t in items or []) + "</ol>"


def _contact_links(value) -> str:
    return re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                  lambda m: f'<a href="mailto:{m.group(0)}">{m.group(0)}</a>', h(value))


def ficha(row: dict, d: dict, accounts: dict, text: str) -> str:
    """Bloco "Entrada da Cordeiro" + "Ficha do executivo" (8 tópicos), como na newsletter."""
    origin = d.get("origin", "automatica")
    origin_tag = ('<span class="cord-origin newsletter">Ficha pesquisada</span>' if origin == "newsletter"
                  else '<span class="cord-origin automatica">Ficha preliminar</span>')

    overview = (f"<h4>Fase atual</h4><p>{h(d.get('phaseDetail'))}</p>"
                f"<h4>Quando a Cordeiro entra</h4><p>{h(d.get('entry'))}</p>"
                f"<h4>Serviço potencial</h4><p>{h(d.get('need'))}</p>"
                f"<h4>Primeiro resultado esperado</h4><p>{h(d.get('firstOutcome'))}</p>")

    timing = d.get("stepTiming") or []
    steps = ""
    for i, t in enumerate(d.get("steps") or [], 1):
        e = timing[i - 1] if i <= len(timing) else {}
        steps += (f'<details class="cord-route-step"><summary>Passo {i} · {h(e.get("title"))} · {h(e.get("internal"))}'
                  f"</summary><div><h4>O que fazer</h4><p>{h(t)}</p><h4>Quando iniciar</h4><p>{h(e.get('start'))}</p>"
                  f"<h4>Espera e fatores que alteram o prazo</h4><p>{h(e.get('external'))}</p>"
                  f"<h4>Como saber que avançou</h4><p>{h(e.get('done'))}</p></div></details>")
    refs = {e["reference"]["url"]: e["reference"] for e in timing if e.get("reference")}
    refs_html = ("<p>As fontes explicam exigências e dependências. As faixas de esforço interno são estimativas de "
                 "planejamento, não prazos publicados pelos clientes.</p>" +
                 "".join(f'<p><a href="{h(r["url"])}" target="_blank" rel="noopener">{h(r["name"])} ↗</a></p>'
                         for r in refs.values()))
    route = (f'<p class="cord-agenda-note">{h(d.get("durationMethod"))}</p>{steps}'
             f"{_topic('Pesquisa e limites das estimativas', refs_html)}"
             f"<h4>Critério para avançar</h4><p>{h(d.get('trigger'))}</p>")

    contacts = ""
    for key in d.get("accounts") or []:
        a = accounts.get(key)
        if not a:
            continue
        portal = (f'<p>Procedimento público localizado.</p><p><a href="{h(a.get("portal"))}" target="_blank" '
                  f'rel="noopener">Abrir cadastro ↗</a></p>' if a.get("portal")
                  else "<p>Solicitar o procedimento oficial ao contratante.</p>")
        contacts += (f'<div class="cord-company"><b>{h(a.get("name"))}</b><p>{h(a.get("about"))}</p>'
                     f'<p>{_contact_links(a.get("channel"))}</p><small>{h(a.get("kind"))}</small>'
                     f'<p><a href="{h(a.get("url"))}" target="_blank" rel="noopener">Canal oficial ↗</a></p>'
                     f'<details class="cord-register"><summary>Como cadastrar a Cordeiro</summary>{portal}'
                     f'{_ol(a.get("guide"))}</details></div>')
    docs = ("<ul>" + "".join(f"<li>{h(x)}</li>" for x in DOCS_TO_PREPARE) + "</ul>"
            "<p>A lista definitiva depende do portal ou edital.</p>")
    contacts_body = (f"<h4>Quem procurar</h4><p>{h(d.get('buyerTarget'))}</p>"
                     + (contacts or "<p>Canal específico ainda não localizado. Confirmar titular e comprador pela "
                                    "fonte da notícia.</p>")
                     + _topic("Documentos para preparar", docs)
                     + '<p class="cord-none">Cadastro apresenta a empresa. Homologação aprova os requisitos. Para '
                       "disputar, confirmar convite ou cotação aberta.</p>")

    companies = "".join(f'<div class="cord-company"><b>{h(c.get("name"))}</b><span>{h(c.get("role"))}</span>'
                        f'<span>{h(c.get("status"))}</span></div>' for c in d.get("companies") or [])
    if not companies:
        companies = "<p>Empresas envolvidas ainda não identificadas.</p>"
    companies += f'<p class="cord-none"><b>Cotadas / pré-selecionadas:</b> {h(d.get("bidStatus"))}</p>'

    follow = ("<ul>" + "".join(f"<li>{h(g)}</li>" for g in d.get("gaps") or []) + "</ul>"
              f"<h4>Quando retomar</h4><p>{h(d.get('followup'))}</p>"
              "<p>Registrar no CRM comprador, CNPJ, pacote, situação do cadastro, prazo de cotação, responsável e "
              "próxima ação. Mobilizar após pedido/contrato aprovado.</p>")
    srcs = "".join(f'<p><a href="{h(x.get("url"))}" target="_blank" rel="noopener">{h(x.get("name"))} ↗</a></p>'
                   for x in d.get("sources") or [])
    sources = (f"<p>{h(d.get('checked'))}</p><p>Serviços e ações são recomendações comerciais. Disponibilidade de "
               "cada pacote depende de confirmação com o contratante.</p>"
               f'<p><a href="{h(row.get("url"))}" target="_blank" rel="noopener">Notícia original ↗</a></p>{srcs}')
    copy = (f'<details class="cord-topic cord-copy"><summary>Copiar ficha completa</summary><div class="cord-topic-body">'
            f"<small>Clique no texto, use Ctrl+A e Ctrl+C.</small><textarea readonly>{h(text)}</textarea></div></details>")

    return (
        '<section class="cord-action" aria-label="Plano comercial para a Cordeiro">'
        f'<div class="cord-summary"><strong>Entrada da Cordeiro · {h(d.get("priority"))}{origin_tag}</strong>'
        f'<p>{h(d.get("phase"))}</p><span class="cord-status">{h(d.get("executor"))}</span></div>'
        '<details class="cord-dossier"><summary>Ficha do executivo</summary><div class="cord-dossier-body">'
        + _topic("1. Entender a oportunidade", overview)
        + _topic("2. Roteiro e tempo estimado por passo", route)
        + _topic("3. Contatos e cadastro", contacts_body)
        + _topic("4. Perguntas para qualificar o serviço", _ol(d.get("questions")))
        + _topic("5. Mensagem de abordagem", f'<p class="cord-template">{h(d.get("message"))}</p>')
        + _topic("6. Empresas envolvidas e seleção", companies)
        + _topic("7. Pendências e acompanhamento", follow)
        + _topic("8. Fontes e confirmação", sources)
        + copy + "</div></details></section>"
    )


def card(row, is_new: bool = False, ficha_html: str = "", images: list[str] | None = None) -> str:
    pot = row.get("potential") or "—"
    pc = POT_CLASS.get(pot, "pot-baixo")
    cat = row.get("category") or ""
    vert = row.get("vertical") or ""
    ufs = [u for u in str(row.get("ufs") or "").split(",") if u]
    uf_tags = "".join(f'<span class="rc-tag uf">{h(UF_LABEL.get(u, u))}</span>' for u in ufs)
    vert_tag = f'<span class="rc-tag vert" style="color:{VERT_COLORS.get(vert, "#4a6a86")}">{h(vert)}</span>' if vert else ""
    cat_tag = (f'<span class="rc-tag cat"><span class="dot" style="background:{CAT_COLORS.get(cat, "#7c8b86")}"></span>'
               f"{h(cat)}</span>")
    new_badge = '<span class="rc-new">Novo</span>' if is_new else ""
    impact = ""
    if row.get("impacto"):
        impact = (
            '<div class="rc-impact"><div class="head">💡 Impacto para a Cordeiro</div>'
            f'<span class="demand">Demanda de guindaste/área: {h(row.get("demand"))}</span>'
            f'<p>{h(row.get("impacto"))}</p></div>'
        )
    engine = ENGINE_LABEL.get(row.get("engine"), row.get("engine") or "")
    signal = f'<span class="rc-signal">{h(row.get("signal_type"))}</span>' if row.get("signal_type") else ""
    prazo = f'<span class="rc-tag eng">Prazo: {h(row.get("prazo"))}</span>' if row.get("prazo") else ""
    published = fmt_date(row.get("published_at")) if row.get("published_at") else "pub. n/d"
    return (
        f'<article class="rc-card {pc}">'
        + (f'<img class="rc-img" src="{h(images[0])}" alt="" loading="lazy">' if images else "") +
        f'<div class="rc-card-top"><div class="rc-tags">{vert_tag}{cat_tag}{uf_tags}</div>{new_badge}</div>'
        f'<h3><a href="{h(row.get("url"))}" target="_blank" rel="noopener">{h(row.get("title") or "(sem título)")}</a></h3>'
        f'<p class="summary">{h(row.get("summary"))}</p>'
        f"{impact}{ficha_html}"
        f'<div class="rc-tags"><span class="rc-tag pot {pc}">{h(pot)}</span>{prazo}{signal}</div>'
        f'<div class="rc-term">Termo: “{h(row.get("term"))}” · <span class="rc-tag eng">{h(engine)}</span></div>'
        f'<div class="rc-meta"><span>{h(row.get("source"))}</span><span>{published}</span></div>'
        "</article>"
    )


def grid(cards: list[str]) -> str:
    return f'<div class="rc-grid">{"".join(cards)}</div>'


def empty(msg: str) -> str:
    return f'<div class="rc-empty">{h(msg)}</div>'


def exa_meter(used: int, limit: int) -> str:
    pct = 0 if not limit else min(100, round(used / limit * 100))
    return (
        '<div class="rc-meter"><div class="lbl">Buscas Exa hoje</div>'
        f'<div class="val">{used} / {limit}</div><div class="trk"><i style="width:{pct}%"></i></div>'
        f"<small>{max(0, limit - used)} restante(s). O contador zera à meia-noite (America/Fortaleza).</small></div>"
    )


def footer(info: str) -> str:
    return (f'<div class="rc-foot"><span>Painel de uso interno — Inteligência de Mercado, Grupo Cordeiro</span>'
            f"<span>{h(info)}</span></div>")
