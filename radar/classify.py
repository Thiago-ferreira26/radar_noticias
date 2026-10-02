"""Classificação automática por regras (sem IA), seguindo os critérios da newsletter.

Atribui categoria, vertical, UF, potencial, demanda, prazo, tipo de sinal e um texto de
impacto para a Cordeiro. É uma triagem: o analista deve validar antes de prospectar.
"""
from __future__ import annotations

import re
import unicodedata

from . import config

CATEGORIES = ["Energia", "Portos", "Mineração", "Óleo & Gás", "Industrial",
              "Logística/Hidrovias", "Saneamento", "Infraestrutura"]

# Palavras-chave (sem acento, minúsculas). A ordem de CATEGORIES desempata.
CATEGORY_KW = {
    "Energia": ["eolic", "eolica", "solar", "fotovolta", "hidrogenio verde", "h2v", "usina", "termeletric",
                "linha de transmissao", "linhas de transmissao", "subestac", "aerogerador", "energia renovavel",
                "complexo eolico", "parque eolico", "offshore", "bateria", "armazenamento de energia"],
    "Portos": ["porto", "portuari", "terminal portuario", "terminal de conteineres", "mucuripe", "cais", "berco", "dragagem",
               "retroportuari", "vila do conde", "itaqui", "suape"],
    "Mineração": ["minera", "minerio", "mina ", "lavra", "litio", "cobre", "niquel", "ouro", "bauxita",
                  "carajas", "siderurg", "aco ", "pelotiz", "fertilizante", "fosfato", "potassio"],
    "Óleo & Gás": ["petroleo", "gas natural", "refinaria", "fpso", "petrobras", "gasoduto", "margem equatorial",
                   "gnl", "oleo e gas"],
    "Industrial": ["fabrica", "industria", "planta industrial", "unidade fabril", "galpao", "data center",
                   "datacenter", "laminadora", "galvaniz", "projetos industriais", "montadora", "cimenteira", "celulose", "polo industrial", "zpe"],
    "Logística/Hidrovias": ["hidrovia", "ferrovia", "transnordestina", "ferrograo", "fiol", "logistic",
                            "porto seco", "rodovia", "duplicacao", "ponte", "aeroporto"],
    "Saneamento": ["saneamento", "adutora", "dessaliniz", "esgoto", "estacao de tratamento", "abastecimento de agua"],
    "Infraestrutura": ["obra", "infraestrutura", "viaduto", "pre-moldad", "concessao", "ppp"],
}

STRONG_CATEGORIES = {"Energia", "Portos", "Mineração", "Óleo & Gás", "Saneamento"}

VERTICAL_BY_CATEGORY ={"Energia": "Energia", "Mineração": "Minerais", "Óleo & Gás": "Minerais"}

NEED_BY_CATEGORY = {
    "Energia": "Içamento de torres, naceles e pás, montagem de estruturas, transformadores e subestações; área para pré-montagem e armazenagem.",
    "Portos": "Movimentação de cargas de projeto, montagem de estruturas e equipamentos portuários; área retroportuária para estocagem.",
    "Mineração": "Montagem de plantas de beneficiamento, britadores e estruturas metálicas; manutenção de equipamentos pesados.",
    "Óleo & Gás": "Montagem de tanques, tubovias e módulos; cargas de projeto em terminais e bases de apoio.",
    "Industrial": "Descarga e montagem de linha fabril, equipamentos e estruturas metálicas.",
    "Logística/Hidrovias": "Içamento de vigas, aparelhos de apoio e estruturas; movimentação de cargas pesadas em terminais.",
    "Saneamento": "Assentamento de tubulações de grande diâmetro e montagem de estações (ETA/ETE, dessalinização).",
    "Infraestrutura": "Içamento de vigas, pré-moldados e estruturas em obras civis.",
}

# Indica relação prática com içamento / carga pesada.
CRANE_KW = ["obra", "constru", "implant", "instala", "fabrica", "usina", "parque", "porto", "terminal", "mina",
            "montagem", "expans", "ampliac", "planta", "linha de transmissao", "subestac", "ferrovia", "ponte",
            "investimento", "complexo", "aerogerador", "torre", "galpao", "data center", "refinaria", "adutora",
            "dessaliniz", "pelotiz", "siderurg", "estaleiro", "duplicac", "modernizac", "unidade",
            "gasoduto", "transmissao", "dragagem", "saneamento", "ppp", "hub", "bateria", "termica", "terminal",
            "laminadora", "rodoviari", "ferroviari", "arrendamento"]
# Conteúdo sem obra (regulatório, macro, mercado financeiro).
LOW_KW = ["regulament", "resolucao", "aneel aprova reajuste", "tarifa", "bolsa de valores", "dividendos",
          "cotacao", "inflacao", "selic", "opiniao", "artigo:", "podcast"]
PENDING_KW = ["estudo", "estuda", "avalia", "planeja", "pretende", "preve", "previsto", "consulta publica",
              "edital", "leilao", "licitac", "memorando", "protocolo de intencoes", "intencao", "proposta",
              "viabilidade", "licenca previa", "pode receber", "negocia", "em analise"]
ONGOING_KW = ["obras em andamento", "inicio das obras", "inicia obras", "iniciou as obras", "comecam as obras",
              "em construcao", "canteiro", "contrato assinado", "assina contrato", "ordem de servico",
              "investimento aprovado", "aprova investimento", "decisao final de investimento", "licenca de instalacao",
              "pedra fundamental", "em implantacao", "inaugura", "contratad", "vence leilao", "arremat",
              "obras comecam", "obras da", "obras do"]
AUCTION_KW = ["leilao", "edital", "licitac", "consulta publica"]

UF_NAMES = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
    "distrito federal": "DF", "espirito santo": "ES", "goias": "GO", "maranhao": "MA", "mato grosso do sul": "MS",
    "mato grosso": "MT", "minas gerais": "MG", "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE",
    "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS",
    "rondonia": "RO", "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE",
    "tocantins": "TO",
}
# Nomes ambíguos exigem contexto ("no Pará", "do Pará"...), senão "para" (preposição) casaria sempre.
AMBIGUOUS_NAMES = {"para", "parana"}
CITY_UF = {
    "fortaleza": "CE", "pecem": "CE", "caucaia": "CE", "sao goncalo do amarante": "CE", "quixeramobim": "CE",
    "sobral": "CE", "juazeiro do norte": "CE", "maracanau": "CE", "aracati": "CE", "camocim": "CE",
    "belem": "PA", "maraba": "PA", "parauapebas": "PA", "barcarena": "PA", "canaa dos carajas": "PA",
    "santarem": "PA", "vila do conde": "PA", "paragominas": "PA", "juruti": "PA", "oriximina": "PA",
    "sao luis": "MA", "itaqui": "MA", "teresina": "PI", "parnaiba": "PI", "natal": "RN", "mossoro": "RN",
    "joao pessoa": "PB", "recife": "PE", "suape": "PE", "maceio": "AL", "aracaju": "SE", "salvador": "BA",
    "camacari": "BA", "manaus": "AM",
}
UF_CODES = set(UF_NAMES.values())
NORDESTE = {"MA", "PI", "CE", "RN", "PB", "PE", "AL", "SE", "BA"}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return " " + "".join(c for c in text if not unicodedata.combining(c)).lower() + " "


_KW_CACHE: dict[str, re.Pattern] = {}


def _kw(k: str) -> re.Pattern:
    """Palavra-chave casada no início de palavra ("ouro" não casa "tesouro"); espaço final exige fim de palavra."""
    if k not in _KW_CACHE:
        end = r"(?![a-z0-9])" if k.endswith(" ") else ""
        _KW_CACHE[k] = re.compile(r"(?<![a-z0-9])" + re.escape(k.strip()) + end)
    return _KW_CACHE[k]


def _has(text_n: str, kws) -> bool:
    return any(_kw(k).search(text_n) for k in kws)


def detect_category(text_n: str, fallback: str | None = None) -> str:
    scores = {cat: sum(len(_kw(k).findall(text_n)) for k in kws) for cat, kws in CATEGORY_KW.items()}
    scores["Infraestrutura"] *= 0.5  # termos genéricos ("obra") só decidem quando nada mais casa
    best = max(CATEGORIES, key=lambda c: (scores[c], -CATEGORIES.index(c)))
    if scores[best] == 0:
        return fallback if fallback in CATEGORIES else "Infraestrutura"
    return best


def detect_ufs(text: str, text_n: str) -> list[str]:
    found: list[str] = []

    def add(uf):
        if uf not in found:
            found.append(uf)

    for m in re.finditer(r"[(\[/–-]\s?([A-Z]{2})\s?[)\]]|[–-]\s([A-Z]{2})\b|\b([A-Z]{2})\)", text or ""):
        uf = next(g for g in m.groups() if g)
        if uf in UF_CODES:
            add(uf)
    for name, uf in UF_NAMES.items():
        if name in AMBIGUOUS_NAMES:
            if re.search(rf"\b(no|do|ao|pelo|estado do|sul do|sudeste do|oeste do|norte do) {name}\b", text_n):
                add(uf)
        elif re.search(rf"\b{name}\b", text_n):
            if name == "mato grosso" and "mato grosso do sul" in text_n:
                continue
            add(uf)
    for city, uf in CITY_UF.items():
        if re.search(rf"\b{city}\b", text_n):
            add(uf)
    if not found and re.search(r"\bnordeste\b", text_n):
        found.append("NE")
    return found or ["BR"]


def detect_value_millions(text: str) -> float | None:
    best = None
    for m in re.finditer(r"R\$\s?([\d.,]+)\s?(bilh|bi\b|milh|mi\b)", text or "", re.I):
        raw = m.group(1).replace(".", "").replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        value *= 1000 if m.group(2).lower().startswith("bi") else 1
        best = max(best or 0, value)
    return best


def detect_prazo(text_n: str, ongoing: bool) -> str:
    year = config.today().year
    years = sorted({int(y) for y in re.findall(r"\b(20[2-4]\d)\b", text_n) if year <= int(y) <= year + 15})
    if years:
        first = years[0]
        if first <= year + 1:
            return f"Curto ({year}-{year + 1})"
        if first <= year + 3:
            return f"Médio ({year + 2}-{year + 3})"
        return f"Longo ({year + 4}+)"
    return f"Curto ({year}-{year + 1})" if ongoing else "A confirmar"


def classify(title: str, summary: str, theme: str | None = None, cfg: dict | None = None) -> dict:
    cfg = cfg or config.load_config()
    rules = cfg["classificacao"]
    prio = set(rules.get("ufs_prioritarias", []))
    area = prio | set(rules.get("ufs_atuacao", [])) | {"NE"}
    porte = float(rules.get("porte_relevante_milhoes", 100))

    text = f"{title or ''}. {summary or ''}"
    text_n = norm(text)
    category = detect_category(text_n, fallback=theme)
    vertical = VERTICAL_BY_CATEGORY.get(category, "Infraestrutura")
    ufs = detect_ufs(text, text_n)
    value = detect_value_millions(text)
    pending = _has(text_n, PENDING_KW)
    ongoing = _has(text_n, ONGOING_KW)
    # Setores pesados já indicam içamento por si; Industrial/Infra precisam de uma palavra de obra.
    heavy = category in STRONG_CATEGORIES and _has(text_n, CATEGORY_KW[category])
    crane = (heavy or _has(text_n, CRANE_KW)) and not (_has(text_n, LOW_KW) and not ongoing)

    # Regras na ordem dos critérios da newsletter — a primeira que se encaixa define o teto.
    if not crane:
        potential = "Baixo"
    elif ufs == ["BR"] or not any(u in area for u in ufs):
        potential = "Médio"
    else:
        relevant = value is not None and value >= porte
        in_prio = any(u in prio for u in ufs)
        if ongoing and not (pending and not relevant):
            potential = "Muito Alto" if (in_prio and relevant) else "Alto"
        elif pending or relevant:
            potential = "Alto" if (in_prio or relevant) else "Médio"
        else:
            potential = "Médio"

    if potential == "Baixo":
        demand = "Não"
    elif potential in ("Muito Alto", "Alto") and ongoing:
        demand = "Sim"
    else:
        demand = "Possível"

    if ongoing:
        signal = "Obra em andamento / investimento aprovado"
    elif _has(text_n, AUCTION_KW):
        signal = "Leilão / edital"
    elif pending:
        signal = "Projeto em estudo / decisão pendente"
    elif value:
        signal = "Investimento anunciado"
    else:
        signal = "Sinal de mercado"

    impacto = NEED_BY_CATEGORY[category] if potential != "Baixo" else (
        "Sem relação prática identificada com içamento ou movimentação de carga pesada.")
    extras = []
    if value:
        if value >= 1000:
            shown = f"{value / 1000:,.1f} bi"
        else:
            shown = f"{value:,.2f} mi" if value < 10 else f"{value:,.0f} mi"
        shown = shown.replace(",", "_").replace(".", ",").replace("_", ".").replace(",0 bi", " bi")
        extras.append(f"Valor citado: R$ {shown}")
    if ufs != ["BR"]:
        extras.append("UF: " + ", ".join(ufs))
    if extras:
        impacto += " " + " · ".join(extras) + "."

    return {
        "category": category,
        "vertical": vertical,
        "ufs": ",".join(ufs),
        "potential": potential,
        "demand": demand,
        "prazo": detect_prazo(text_n, ongoing),
        "signal_type": signal,
        "impacto": impacto,
    }


def is_excluded(title: str, summary: str, cfg: dict) -> bool:
    text_n = norm(f"{title} {summary}")
    return any(norm(w).strip() in text_n for w in cfg.get("excluir_se_contiver", []) or [] if w)
