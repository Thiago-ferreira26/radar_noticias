"""Nota de 0 a 10: vale a pena o executivo jogar esta notícia no Bitrix?

Mede a chance de a notícia virar relacionamento e demanda para a Cordeiro, pelo fluxo comercial:
executivo envia ao Bitrix → Inteligência pesquisa empresas e contatos → executivo inicia o relacionamento.

Seis critérios; cada um vale até o seu peso (pesos em config "nota", somando 10) e cada nível
é uma fração desse peso. A ficha pesquisada (newsletter) prevalece sobre a estimativa automática.
"""
from __future__ import annotations

import re
from datetime import date

from . import config
from .classify import detect_value_millions, norm

CRITERIA = {  # chave: (rótulo, peso padrão)
    "demanda": ("Demanda de guindaste/área", 2.5),
    "fase": ("Momento da obra", 2.5),
    "regiao": ("Região", 1.5),
    "contato": ("Empresas para contatar", 1.5),
    "porte": ("Porte do investimento", 1.0),
    "prazo": ("Prazo", 1.0),
}

DEMAND_LEVEL = {"Sim": (1.0, "Demanda Sim"), "Possível": (0.48, "Demanda possível"), "Não": (0.0, "Sem demanda")}

# Ordem importa: a primeira regra que casa com a fase (ficha) ou o tipo de sinal define o nível.
# A janela ideal para criar relacionamento é antes do pacote de içamento ser contratado.
PHASE_RULES = [
    (r"suspens|bloquead|reavaliac|paralisad|cancelad", 0.3, "Obra travada"),
    (r"epc|contratacao definida|contrato a assinar|fornecimento contratado|leilao vencido|leilao homologado|"
     r"projeto executivo contratado|concessao", 1.0, "Contratação em curso"),
    (r"obra em andamento|em execucao|expansao", 0.6, "Obra em andamento"),
    (r"aprovac|aprovad|licenc|licenca|financiamento|obra prevista|ainda nao iniciada|inicio de obra|confirmad",
     0.92, "Aprovado, perto da obra"),
    (r"edital|leilao|licitac|consulta|pre-habilitac", 0.72, "Leilão/edital"),
    (r"anuncio|anunciado|desenvolvimento|novo investimento", 0.48, "Investimento anunciado"),
    (r"estudo|decisao|viabilidade|embrionari|mapeamento|proposta", 0.28, "Em estudo"),
    (r"sinal de mercado|contexto|panorama", 0.08, "Só contexto"),
]

PRAZO_LEVEL = [("Curto", 1.0), ("Médio", 0.6), ("Longo", 0.2)]

# Donos de obra frequentes no Radar: notícia que cita um deles já tem por onde começar a pesquisa.
OWNERS = ["vale", "petrobras", "hydro", "alcoa", "mrn", "mineracao rio do norte", "csp", "arcelormittal", "eletrobras",
          "neoenergia", "enel", "engie", "cpfl", "equatorial", "cagece", "cosanpa", "suzano", "sinobras",
          "transnordestina", "csn", "aeris", "casa dos ventos", "auren", "voltalia", "statkraft", "iberdrola",
          "edp", "taesa", "isa cteep", "state grid", "copel", "cemig", "eneva", "brasken", "braskem", "gerdau",
          "usiminas", "anglo american", "belo sun", "imerys", "cimento apodi", "votorantim", "intercement",
          "fortescue", "pecem", "complexo do pecem", "cipp", "vli", "rumo", "hidrovias do brasil", "cargill",
          "bunge", "amaggi", "atem", "norte energia", "ambipar", "aegea", "sabesp", "marquise", "dpw", "apm",
          "porto de itaqui", "emap", "cdp", "companhia docas", "white martins", "fortlev", "m. dias branco"]
OWNER_RE = re.compile(r"\b(" + "|".join(re.escape(o) for o in OWNERS) + r")\b")
COMPANY_RE = re.compile(r"\b(s\.?a\.?|ltda|grupo [a-z]|consorcio|construtora|engenharia)\b")
NOT_IDENTIFIED = ("nao identificad", "responsavel nao identificad", "nao confirmad", "a confirmar")

BANDS = [(8.0, "Quente", "#b3261e"), (6.0, "Morna", "#c9761a"), (4.0, "Fria", "#3d6f8f"), (0.0, "Baixa", "#7c8b86")]


def weights(cfg: dict | None = None) -> dict[str, float]:
    """Pesos da configuração, reescalados para somar 10."""
    raw = ((cfg or config.load_config()).get("nota") or {}).get("pesos") or {}
    w = {k: max(0.0, float(raw.get(k, default))) for k, (_, default) in CRITERIA.items()}
    total = sum(w.values()) or 1.0
    return {k: v * 10 / total for k, v in w.items()}


def band(score: float) -> tuple[str, str]:
    for limit, name, color in BANDS:
        if score >= limit:
            return name, color
    return BANDS[-1][1:]


# Título dizendo que a obra acabou: o guindaste já foi contratado (vale só se a ficha não foi pesquisada).
DONE_RE = re.compile(r"\b(inaugur|inicia operac|entra em operac|comeca a operar|conclui|concluid)")


DONE_CAP = 4.5


def _phase(row: dict, ficha: dict) -> tuple[float, str]:
    researched = ficha.get("origin") == "newsletter"
    if not researched and DONE_RE.search(norm(row.get("title") or "")):
        return 0.15, "Obra concluída"
    text = norm(" ".join(filter(None, [ficha.get("phase") if researched else None, row.get("signal_type")])))
    for pattern, level, label in PHASE_RULES:
        if re.search(pattern, text):
            return level, label
    return 0.2, "Fase a confirmar"


def _region(ufs: list[str], cfg: dict) -> tuple[float, str]:
    rules = cfg["classificacao"]
    prio = set(rules.get("ufs_prioritarias", []))
    area = set(rules.get("ufs_atuacao", [])) | {"NE"}
    if any(u in prio for u in ufs):
        return 1.0, "/".join(u for u in ufs if u in prio)
    if any(u in area for u in ufs):
        return 0.6, "Nordeste"
    if not ufs or ufs == ["BR"]:
        return 0.2, "Nacional"
    return 0.1, "Fora da área"


def _contact(row: dict, ficha: dict, text_n: str) -> tuple[float, str]:
    if ficha.get("origin") == "newsletter":
        executor = norm(ficha.get("executor") or "")
        companies = ficha.get("companies") or []
        if executor and not executor.startswith(NOT_IDENTIFIED):
            return 1.0, "Executora identificada"
        if companies:
            return 0.53, "Empresas mapeadas"
    if OWNER_RE.search(text_n) or COMPANY_RE.search(text_n):
        return 0.4, "Empresa citada"
    return 0.0, "Sem empresa citada"


def _porte(text: str) -> tuple[float, str]:
    value = detect_value_millions(text)
    if value is None:
        return 0.2, "Sem valor"
    shown = f"R$ {value / 1000:.1f} bi".replace(".", ",").replace(",0 bi", " bi") if value >= 1000 else f"R$ {value:.0f} mi"
    return (1.0 if value >= 1000 else 0.7 if value >= 100 else 0.3), shown


def _prazo(prazo: str | None) -> tuple[float, str]:
    for prefix, level in PRAZO_LEVEL:
        if (prazo or "").startswith(prefix):
            return level, f"Prazo {prefix.lower()}"
    return 0.4, "Prazo a confirmar"


def _age_penalty(sort_date, today: date) -> float:
    try:
        days = (today - date.fromisoformat(str(sort_date)[:10])).days
    except ValueError:
        return 0.0
    return 1.0 if days > 120 else 0.5 if days > 60 else 0.0


def score(row: dict, ficha: dict | None = None, cfg: dict | None = None, w: dict | None = None,
          today: date | None = None) -> dict:
    """{"nota": 0–10, "faixa": Quente/Morna/Fria/Baixa, "motivos": texto curto, "detalhe": pontos por critério}."""
    cfg = cfg or config.load_config()
    w = w or weights(cfg)
    ficha = ficha or {}
    text = " ".join(str(row.get(k) or "") for k in ("title", "summary", "impacto"))
    text_n = norm(text)
    ufs = [u for u in str(row.get("ufs") or "").split(",") if u]
    parts = {
        "demanda": DEMAND_LEVEL.get(row.get("demand"), (0.48, "Demanda a confirmar")),
        "fase": _phase(row, ficha),
        "regiao": _region(ufs, cfg),
        "contato": _contact(row, ficha, text_n),
        "porte": _porte(text),
        "prazo": _prazo(row.get("prazo")),
    }
    detail = {k: round(w[k] * level, 2) for k, (level, _) in parts.items()}
    penalty = _age_penalty(row.get("sort_date") or row.get("published_at") or row.get("collected_at"),
                           today or config.today())
    total = round(min(10.0, max(0.0, sum(detail.values()) - penalty)), 1)
    if parts["fase"][1] == "Obra concluída":  # obra pronta: no máximo monitorar (fases futuras, manutenção)
        total = min(total, DONE_CAP)
    reasons = [label for k, (level, label) in parts.items() if level > 0.25]
    if penalty:
        reasons.append(f"notícia antiga (−{penalty:g})")
    return {"nota": total, "faixa": band(total)[0], "motivos": " · ".join(reasons), "detalhe": detail}
