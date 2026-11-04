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

# Necessidade por tipo de projeto dentro de cada área: a primeira linha cujas palavras aparecem no texto vale;
# se nenhuma casar, fica o texto genérico de NEED_BY_CATEGORY.
NEED_BY_TYPE = {
    "Energia": [
        (["eolica offshore", "eolicas offshore", "eolico offshore"],
         "Eólica no mar: guindastes no porto de apoio para pré-montagem e embarque de torres, naceles e pás; área retroportuária para estoque de componentes."),
        (["eolic", "aerogerador", "parque eolico", "complexo eolico"],
         "Içamento de torres, naceles e pás dos aerogeradores (guindastes de grande porte); área para pré-montagem e estoque de componentes."),
        (["solar", "fotovolta"],
         "Descarga e distribuição de módulos, estruturas (trackers) e inversores; içamento de transformadores da subestação; área para estoque de material."),
        (["linha de transmissao", "linhas de transmissao", "subestac", "transmissao"],
         "Montagem de torres treliçadas e lançamento de cabos; içamento de transformadores e reatores nas subestações."),
        (["hidrogenio", "h2v", "eletroliz", "amonia verde"],
         "Montagem de eletrolisadores, tanques e módulos de processo; cargas de projeto recebidas pelo porto."),
        (["bateria", "armazenamento de energia", "bess"],
         "Içamento de contêineres de baterias (BESS), transformadores e inversores; área para estoque dos módulos."),
        (["nuclear", "reator", "angra 3"],
         "Cargas superpesadas (vaso do reator, geradores de vapor) e montagem de estruturas de grande porte."),
        (["termeletric", "termica", "usina a gas", "ciclo combinado", "biomassa"],
         "Içamento de turbinas, geradores, caldeiras e transformadores; montagem da estrutura da casa de força."),
        (["hidreletric", "pch "],
         "Içamento de turbinas, geradores e comportas; montagem de pontes rolantes da casa de força."),
    ],
    "Portos": [
        (["terminal de conteineres", "conteiner", "porteiner", "tecon"],
         "Montagem de portêineres e transtêineres (STS/RTG); movimentação de equipamentos e estruturas do pátio."),
        (["glp", "gnl", "combustiveis", "granel liquido", "graneis liquidos", "tancagem"],
         "Montagem de tanques, esferas e tubovias do terminal; içamento de braços de carregamento; cargas de projeto pelo cais."),
        (["granel", "graneis", "minerio", "graos", "fertilizante"],
         "Montagem de carregadores de navio, correias transportadoras e silos; área retroportuária para estoque."),
        (["dragagem"],
         "A dragagem em si usa dragas; a demanda de guindaste vem das obras ligadas a ela (cais, berços, defensas) e do apoio no canteiro."),
        (["cais", "berco", "pier", "atracac"],
         "Cravação de estacas e içamento de vigas e pré-moldados do cais; montagem de defensas e equipamentos portuários."),
    ],
    "Mineração": [
        (["siderurg", "aco ", "laminadora", "laminacao", "alto-forno", "alto forno"],
         "Montagem de altos-fornos, laminadores e pontes rolantes; cargas pesadas de equipamentos industriais."),
        (["pelotiz"],
         "Montagem de fornos, discos de pelotamento e correias; estruturas metálicas da usina de pelotização."),
        (["fertilizante", "fosfato", "potassio"],
         "Montagem da planta química: reatores, tanques, silos e estruturas metálicas."),
        (["pesquisa mineral", "sondagem", "novos alvos", "alvos de", "descoberta", "reservas", "estimativa de recursos"],
         "Fase de pesquisa mineral: pouca demanda agora (sondagem). A demanda vem quando a mina e a planta forem implantadas."),
        (["refinaria de alumina", "alumina", "aluminio"],
         "Montagem de digestores, calcinadores e tanques; cargas pesadas de equipamentos da refinaria."),
    ],
    "Óleo & Gás": [
        (["refinaria", "refino"],
         "Montagem de torres de destilação, reatores, vasos e tubovias; cargas superpesadas de projeto."),
        (["gasoduto", "oleoduto"],
         "Lançamento de tubos (sidebooms e guindastes), travessias e montagem de estações de compressão e entrega."),
        (["gnl", "regaseific"],
         "Montagem de tanques criogênicos, braços de carregamento e tubovias; cargas de projeto pelo porto."),
        (["glp", "terminal de combustiveis", "tancagem", "base de distribuicao"],
         "Montagem de tanques, esferas e tubovias; içamento de bombas e equipamentos do terminal."),
        (["fpso", "plataforma", "sonda", "offshore", "margem equatorial", "bloco ", "blocos", "pre-sal", "poco "],
         "Atividade no mar: a demanda em terra fica nas bases de apoio portuário (movimentação de cargas, módulos e equipamentos)."),
    ],
    "Industrial": [
        (["data center", "datacenter"],
         "Içamento de geradores, chillers, transformadores e módulos de energia; montagem da estrutura metálica do prédio."),
        (["celulose", "papel e celulose", "fabrica de papel"],
         "Montagem de caldeira de recuperação, digestor e máquinas de papel; cargas superpesadas."),
        (["cimento", "cimenteira", "clinquer"],
         "Montagem de forno rotativo, moinhos e silos; estruturas metálicas da fábrica."),
        (["montadora", "automotiv", "veiculos"],
         "Instalação de linhas de produção, prensas e robôs; montagem de estrutura metálica e pontes rolantes."),
        (["galvaniz", "metalurg", "fundicao"],
         "Instalação de fornos, tanques e pontes rolantes; montagem de estruturas metálicas."),
        (["galpao", "galpoes", "centro de distribuicao", "condominio logistico"],
         "Montagem de estruturas metálicas e pré-moldados do galpão; descarga de equipamentos."),
    ],
    "Logística/Hidrovias": [
        (["ferrovia", "ferroviari", "transnordestina", "ferrograo", "fiol", "fico "],
         "Lançamento de vigas de pontes e viadutos ferroviários; descarga de trilhos e dormentes; montagem de pátios e terminais."),
        (["ponte", "viaduto"],
         "Içamento de vigas longarinas e aduelas pré-moldadas; montagem de aparelhos de apoio."),
        (["aeroporto"],
         "Montagem de estruturas metálicas do terminal, pontes de embarque e equipamentos de pátio."),
        (["hidrovia", "fluvial", "balsa"],
         "Montagem de terminais fluviais e estruturas de atracação; movimentação de cargas em balsas."),
        (["porto seco", "terminal multimodal", "terminal intermodal"],
         "Movimentação de contêineres e montagem de silos, estruturas e equipamentos do terminal."),
        (["rodovia", "duplicac", "br-"],
         "Içamento de vigas de pontes e viadutos; pré-moldados (galerias, defensas) ao longo do trecho."),
    ],
    "Saneamento": [
        (["dessaliniz"],
         "Montagem de módulos de osmose reversa, tanques e captação no mar; assentamento de tubos de grande diâmetro."),
        (["adutora", "tubulac", "ramal"],
         "Assentamento de tubos de grande diâmetro e montagem de estações elevatórias."),
        (["esgot", "ete "],
         "Montagem de estações de tratamento de esgoto (ETE) e elevatórias; assentamento de interceptores e emissários."),
        (["abastecimento de agua", "eta ", "reservatorio"],
         "Montagem de estações de tratamento de água (ETA), reservatórios e elevatórias."),
        (["barragem", "acude"],
         "Montagem de comportas, tomadas d'água e estruturas de concreto; movimentação de equipamentos pesados."),
    ],
    "Infraestrutura": [
        (["iluminacao publica", "luminaria", "led "],
         "Troca de postes e luminárias: serviço de caminhão munck, pouca demanda de guindaste."),
        (["hospital", "escola", "edificio", "predio", "arena", "estadio", "centro de eventos"],
         "Içamento de estruturas metálicas e pré-moldados da edificação; guindaste para cobertura e equipamentos."),
        (["viaduto", "ponte", "pre-moldad", "passarela"],
         "Içamento de vigas e pré-moldados; montagem de aparelhos de apoio."),
        (["drenagem", "pavimentac", "contencao de encostas", "encosta"],
         "Obras urbanas de drenagem e pavimentação: pouca demanda de guindaste (no máximo galerias pré-moldadas)."),
    ],
}


# Valem em qualquer área (a categoria às vezes vem do termo de busca, ex.: iluminação no acesso a um porto).
ANY_CATEGORY_NEEDS = [
    (["iluminacao publica", "iluminacao led", "luminaria"],
     "Troca de postes e luminárias: serviço de caminhão munck, pouca demanda de guindaste."),
]


def need_for(category: str, text_n: str) -> str:
    """Necessidade provável de guindaste/área para o tipo de projeto da notícia."""
    for kws, need in ANY_CATEGORY_NEEDS + NEED_BY_TYPE.get(category, []):
        if _has(text_n, kws):
            return need
    return NEED_BY_CATEGORY[category]

# Indica relação prática com içamento / carga pesada.
CRANE_KW = ["obra", "constru", "implant", "instala", "fabrica", "usina", "parque", "porto", "terminal", "mina",
            "montagem", "expans", "ampliac", "planta", "linha de transmissao", "subestac", "ferrovia", "ponte",
            "investimento", "complexo", "aerogerador", "torre", "galpao", "data center", "refinaria", "adutora",
            "dessaliniz", "pelotiz", "siderurg", "estaleiro", "duplicac", "modernizac", "unidade",
            "gasoduto", "transmissao", "dragagem", "saneamento", "ppp", "hub", "bateria", "termica", "terminal",
            "laminadora", "rodoviari", "ferroviari", "arrendamento"]
# Conteúdo sem obra (regulatório, macro, mercado financeiro).
LOW_KW = ["regulament", "resolucao", "aneel aprova reajuste", "tarifa", "bolsa de valores", "dividendos",
          "cotacao", "inflacao", "selic", "artigo de opiniao", "artigo:", "podcast",
          # notícias corporativas/de mercado sem obra (comuns em portais setoriais como o Brasil Mineral)
          "vagas de estagio", "premio", "premiada", "premiado", "seminario", "webinar", "eleva perspectiva",
          "rebaixa perspectiva", "perspectiva positiva", "perspectiva negativa",
          "rating", "ebitda", "trimestre", "bonds", "capta r", "capta us", "rodada pre", "rodada de investimento",
          "consultores", "acoes da", "acoes sobem", "acoes caem", "acoes disparam"]
PENDING_KW = ["estudo", "estuda", "avalia", "planeja", "pretende", "preve", "previsto", "consulta publica",
              "edital", "leilao", "licitac", "memorando", "protocolo de intencoes", "intencao", "proposta",
              "viabilidade", "licenca previa", "pode receber", "negocia", "em analise"]
ONGOING_KW = ["obras em andamento", "em andamento", "rapido andamento", "inicio das obras", "inicia obras", "iniciou as obras", "comecam as obras",
              "em construcao", "contrato assinado", "assina contrato", "ordem de servico",
              "investimento aprovado", "aprova investimento", "decisao final de investimento", "licenca de instalacao",
              "pedra fundamental", "em implantacao", "inaugura", "contratad", "vence leilao", "arremat",
              "obras comecam", "obras da", "obras do"]
CANTEIRO_WORK_KW = ["constru", "implant", "usina", "fabrica", "montagem", "terraplen", "fundac", "ampliac", "duplicac",
                    "parque", "porto", "terminal", "ferrovia", "rodovia", "ponte", "viaduto", "mina ", "planta",
                    "subestac", "linha de transmissao", "adutora", "refinaria", "galpao", "data center"]
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
    # polos de mineração/indústria pesada
    "porto trombetas": "PA", "trombetas": "PA", "carajas": "PA", "alunorte": "PA", "albras": "PA",
    "maraba": "PA", "itaituba": "PA", "caetite": "BA", "lagoa real": "BA", "itabira": "MG", "congonhas": "MG",
    "cariri": "CE", "crato": "CE", "barbalha": "CE",
    # "Porto + nome" é cidade, não porto (ver PLACE_PORTO_RE)
    "porto velho": "RO", "porto alegre": "RS", "porto seguro": "BA", "porto de galinhas": "PE",
}
UF_CODES = set(UF_NAMES.values())
NORDESTE = {"MA", "PI", "CE", "RN", "PB", "PE", "AL", "SE", "BA"}
# Cotação usada para converter valores citados em US$ (porte do investimento); aproximada de propósito.
USD_BRL = 5.4
# Nomes de lugar com "porto" que não são porto: tirados do texto antes de escolher a área e a demanda.
PLACE_PORTO_RE = re.compile(r"(?<![a-z])(porto (velho|alegre|seguro|nacional|real|feliz|calvo|ferreira|das dunas"
                            r"|de galinhas)|cais do porto|fc porto|cidade do porto|voos? para (o )?porto)(?![a-z])")
# Palavras muito comuns em português: texto com poucas delas está em outra língua.
PT_STOPWORDS = set("de da do das dos em no na nos nas para com que uma um por ao os as e o a se mais sobre "
                   "entre ate apos pela pelo sao nao foi tem".split())


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
    if re.search(r"\bPará\b", text or ""):  # com acento e maiúscula é o estado, não a preposição
        add("PA")
    for city, uf in CITY_UF.items():
        if re.search(rf"\b{city}\b", text_n):
            if city == "cariri" and "cariri paraibano" in text_n:
                continue
            add(uf)
    if not found and re.search(r"\bnordeste\b", text_n):
        found.append("NE")
    return found or ["BR"]


def detect_value_millions(text: str) -> float | None:
    """Maior valor citado, em milhões de R$ (valores em US$ convertidos por USD_BRL)."""
    best = None
    for m in re.finditer(r"(R|US)\$\s?([\d.,]+)\s?(bilh|bi\b|milh|mi\b)", text or "", re.I):
        raw = m.group(2).replace(".", "").replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        value *= 1000 if m.group(3).lower().startswith("bi") else 1
        value *= USD_BRL if m.group(1).upper() == "US" else 1
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


# Fora do escopo do Radar: notícias de outros países sem obra no Brasil.
FOREIGN_TLDS = (".pt",)  # Portugal: "Vila do Conde", "Porto" e "Bragança" trazem muitas notícias de lá
FOREIGN_KW = ["portugal", "lisboa", "argentina", "argentino", "milei", "russia", "russo", "ucrania", "estados unidos",
              "eua", "china", "chines", "chinesa", "europa", "europeia", "espanha", "mexico", "chile", "chileno",
              "peru", "colombia", "india", "japao", "alemanha", "hamburgo", "franca", "reino unido", "angola",
              "mocambique", "nord stream", "siria", "gaza", "israel", "venezuela", "venezuelana"]
BRAZIL_KW = ["brasil", "brasileir", "governo federal", "governo lula", "lula", "bndes", "petrobras", "vale ",
             "nordeste", "amazonia", "anp", "aneel", "antaq", "ibama"]


def out_of_scope(title: str, summary: str, url: str | None, ufs: list[str], cfg: dict) -> str | None:
    """Motivo para a notícia ficar fora do Radar (sem relação com a Cordeiro), ou None."""
    host = (url or "").split("/")[2] if (url or "").count("/") >= 2 else ""
    if host.endswith(FOREIGN_TLDS):
        return "Notícia de site estrangeiro, sem obra no Brasil"
    if word := excluded_word(title, summary, cfg):
        return f"Tema fora do escopo do Radar ({word})"
    title_n, text_n = norm(title), norm(f"{title} {summary}")
    if ufs == ["BR"] and _has(title_n, FOREIGN_KW) and not _has(text_n, BRAZIL_KW):
        return "Notícia sobre outro país, sem obra no Brasil"
    if ufs == ["BR"] and foreign_language(text_n) and not _has(text_n, BRAZIL_KW):
        return "Notícia em outra língua, sem relação com o Brasil"
    return None


def foreign_language(text_n: str) -> bool:
    """True se o texto (normalizado) quase não tem palavras comuns do português."""
    words = re.findall(r"[a-z]+", text_n)
    return len(words) >= 8 and sum(w in PT_STOPWORDS for w in words) / len(words) < 0.08


def classify(title: str, summary: str, theme: str | None = None, cfg: dict | None = None,
             url: str | None = None) -> dict:
    cfg = cfg or config.load_config()
    rules = cfg["classificacao"]
    prio = set(rules.get("ufs_prioritarias", []))
    area = prio | set(rules.get("ufs_atuacao", [])) | {"NE"}
    porte = float(rules.get("porte_relevante_milhoes", 100))

    text = f"{title or ''}. {summary or ''}"
    text_n = norm(text)
    ufs = detect_ufs(text, text_n)
    text_n = PLACE_PORTO_RE.sub(" ", text_n)  # "Porto Velho", "Cais do Porto"... não contam como porto
    category = detect_category(text_n, fallback=theme)
    vertical = VERTICAL_BY_CATEGORY.get(category, "Infraestrutura")
    value = detect_value_millions(text)
    pending = _has(text_n, PENDING_KW)
    # "canteiro" só indica obra em andamento junto de uma palavra de obra ("canteiros de obras" numa
    # campanha social não é obra)
    ongoing = _has(text_n, ONGOING_KW) or (_has(text_n, ["canteiro"]) and _has(text_n, CANTEIRO_WORK_KW))
    # Setores pesados já indicam içamento por si; Industrial/Infra precisam de uma palavra de obra.
    heavy = category in STRONG_CATEGORIES and _has(text_n, CATEGORY_KW[category])
    crane = (heavy or _has(text_n, CRANE_KW)) and not (_has(text_n, LOW_KW) and not ongoing)
    scope = out_of_scope(title or "", summary or "", url, ufs, cfg)

    # Regras na ordem dos critérios da newsletter — a primeira que se encaixa define o teto.
    if scope or not crane:
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

    if scope:
        impacto = f"{scope}: sem relação com a Cordeiro."
    elif potential != "Baixo":
        impacto = need_for(category, text_n)
    else:
        impacto = "Sem relação prática identificada com içamento ou movimentação de carga pesada."
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


NO_RELATION_DEMAND = "Não"


def has_relation(demand) -> bool:
    """False para notícias sem relação com a Cordeiro (demanda de guindaste/área = "Não"): ficam no banco,
    mas não aparecem na Visão do dia nem no Modo TV."""
    return (demand or "") != NO_RELATION_DEMAND


def excluded_word(title: str, summary: str, cfg: dict) -> str | None:
    """Primeira palavra/expressão de excluir_se_contiver presente (palavra inteira: "gol" não casa "golfo")."""
    text_n = norm(f"{title} {summary}")
    for w in cfg.get("excluir_se_contiver", []) or []:
        k = norm(str(w)).strip()
        if k and re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", text_n):
            return str(w)
    return None


def is_excluded(title: str, summary: str, cfg: dict) -> bool:
    return excluded_word(title, summary, cfg) is not None
