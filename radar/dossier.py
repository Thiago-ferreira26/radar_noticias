"""Ficha do executivo: plano comercial por notícia, no formato da newsletter Radar Cordeiro.

Duas origens:
  * "newsletter": fichas pesquisadas pelo analista, importadas do HTML da newsletter
    (fase, executor, empresas, contatos e cadastro verificados);
  * "automatica": ficha preliminar gerada pelo roteiro padrão para notícias sem ficha
    pesquisada. Não inventa contatos, executor nem empresas: esses campos ficam "a confirmar".

Importação pela linha de comando:
    python -m radar.dossier radar-cordeiro-relatorio-NEWSLETTER-integrado.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import classify, config, db, engines

# ------------------------------------------------------------- textos-padrão (iguais aos da newsletter)
BASIS = ("Faixa de trabalho interno estimada para planejamento; não é média estatística nem SLA da Cordeiro. "
         "Confirmar com a equipe responsável.")
REF_FORN = {"name": "Eneva: fornecedores", "url": "https://www.eneva.com.br/seja-um-fornecedor/"}
REF_TEC = {"name": "Mammoet: planejamento técnico",
           "url": "https://www.mammoet.com/civil-engineering/prefabricated-construction/"}

STEP_TIMING = [
    {"step": 1, "title": "Abordagem inicial", "internal": "Meio a 1 dia útil", "start": "Canal oficial validado.",
     "external": "Retorno do comprador: prazo não publicado; retomar após 2–3 dias úteis.",
     "done": "Contato encaminhado e próxima conversa combinada.", "reference": REF_FORN},
    {"step": 2, "title": "Qualificar comprador e pacote", "internal": "1–3 dias úteis",
     "start": "Contato do responsável identificado.",
     "external": "Reunião e resposta sobre pacote: confirmar agenda com o comprador.",
     "done": "Comprador, pacote, elegibilidade e prazo de cotação confirmados.", "reference": REF_FORN},
    {"step": 3, "title": "Cadastro e homologação", "internal": "2–5 dias úteis para preparar e enviar",
     "start": "Cadastro aplicável e lista de documentos obtidos.",
     "external": "Análise/homologação: sem prazo geral confirmado; solicitar previsão ao contratante.",
     "done": "Documentos completos enviados; só considerar homologado após aprovação.", "reference": REF_FORN},
    {"step": 4, "title": "Estudo técnico", "internal": "3–7 dias úteis para estudo preliminar",
     "start": "Pesos, dimensões, acessos e janela de trabalho disponíveis; pode ocorrer em paralelo ao cadastro.",
     "external": "Visita e dados: conforme agenda do cliente. Escopo complexo pode exigir 10–20 dias úteis de trabalho ou mais.",
     "done": "Engenharia valida solução, recursos e premissas para a proposta.", "reference": REF_TEC},
    {"step": 5, "title": "Proposta e negociação", "internal": "1–3 dias úteis para elaborar e enviar",
     "start": "Escopo técnico suficiente e condições de participação confirmadas.",
     "external": "Negociação e aprovação: prazo do comprador; não estimar contratação pelo tempo de preparar a proposta.",
     "done": "Proposta protocolada; mobilização somente após pedido/contrato aprovado.", "reference": REF_FORN},
]
STEPS_2_5 = [
    "Identificar quem emite o pedido de guindaste/movimentação e perguntar se o pacote está aberto, adjudicado ou disponível para subcontratação.",
    "Concluir cadastro/homologação com o comprador e reunir referências, frota, acessórios e documentação solicitada.",
    "Solicitar pesos, dimensões, raios, alturas, acessos, piso e calendário; realizar visita e estudo técnico quando cabível.",
    "Enviar proposta técnica e comercial por pacote, incluindo mobilização, equipe, prazo e condições; acompanhar a cotação até pedido/contrato aprovado.",
]
DURATION_METHOD = ("Estimativas provisórias de trabalho por etapa, em dias úteis, a partir dos requisitos indicados. "
                   "Espera externa é separada. Não somar como duração garantida: cadastro e estudo podem ocorrer em "
                   "paralelo. Validar as faixas com Comercial, Cadastro e Engenharia da Cordeiro.")
BUYER_TARGET = ("Comprador de serviços da empresa que emite o pedido + engenheiro/planejador de montagem. Funções "
                "recomendadas; nome e contato direto do comprador ainda não verificados.")
FIRST_OUTCOME = ("Obter nome e canal do comprador, empresa/CNPJ que contrata, situação do pacote, prazo de cotação e "
                 "orientação de cadastro; registrar a resposta no CRM.")
FOLLOWUP_ACTIVE = ("Iniciar em até 2 dias úteis, conforme prioridade da conta; pedir previsão de retorno. Sem resposta, "
                   "retomar após 2 dias úteis pelo canal oficial. Prazo sugerido pela Cordeiro, não compromisso da empresa.")
FOLLOWUP_MONITOR = ("Revisar a fonte e os marcos a cada 15 dias; antecipar a revisão se sair edital, licença, contratação "
                    "ou decisão de investimento. Sugestão comercial.")
BID_STATUS = ("Nenhuma empresa apenas cotada/pré-selecionada foi identificada nas fontes consultadas. As empresas abaixo "
              "são empreendedoras, fornecedoras ou executoras com o status indicado; não constituem lista de concorrentes.")
DOCS_TO_PREPARE = [
    "CNPJ, contrato social e dados comerciais.",
    "Certidões vigentes solicitadas pelo contratante.",
    "Apresentação, frota e tabelas de capacidade.",
    "Referências e atestados compatíveis.",
    "Documentação técnica, de segurança e dos operadores aplicável ao pacote.",
]

PRIORITY_BY_POTENTIAL = {"Muito Alto": "Prospectar", "Alto": "Preparar", "Médio": "Monitorar", "Baixo": "Monitorar"}
PHASE_BY_SIGNAL = {
    "Obra em andamento / investimento aprovado": "Obra em andamento",
    "Leilão / edital": "Leilão / consulta",
    "Projeto em estudo / decisão pendente": "Estudos / decisão pendente",
    "Investimento anunciado": "Anúncio / desenvolvimento",
    "Sinal de mercado": "Contexto / sem projeto qualificável",
}


def questions_for(need: str) -> list[str]:
    return [
        "Qual pacote está aberto, qual empresa emite o pedido e qual é a data prevista de montagem?",
        f"Para este escopo potencial — {need} — quais itens realmente estão previstos e ainda disponíveis?",
        "O serviço está livre para cotar, já contratado ou disponível como subcontratação? Qual empresa foi selecionada e para qual escopo?",
        "Quais cargas, pesos, dimensões, raios/alturas, acessos, piso e janela de trabalho precisam ser atendidos?",
        "Há visita técnica, requisitos de segurança, documentação e equipamentos mínimos?",
        "Qual portal/procedimento, comprador, prazo de proposta, critério de escolha e previsão do pedido?",
    ]


def message_for(title: str) -> str:
    return (f"Olá, sou [nome], executivo de vendas do Grupo Cordeiro. Sobre “{title}”, gostaria de confirmar o "
            "responsável pela contratação de içamento, movimentação e montagem. Qual pacote está aberto, qual empresa "
            "emite o pedido e qual é a data prevista de montagem? Podemos apresentar frota, referências e estudar as "
            "cargas. Qual é o procedimento de homologação e o prazo para participar da cotação?")


def auto_dossier(row: dict) -> dict:
    """Ficha preliminar a partir da notícia e da classificação automática (sem pesquisa de contatos)."""
    need = classify.NEED_BY_CATEGORY.get(row.get("category"), classify.NEED_BY_CATEGORY["Infraestrutura"])
    priority = PRIORITY_BY_POTENTIAL.get(row.get("potential"), "Monitorar")
    phase = PHASE_BY_SIGNAL.get(row.get("signal_type"), "Contexto / sem projeto qualificável")
    collected = ui_date(row.get("collected_at"))
    return {
        "origin": "automatica",
        "priority": priority,
        "phase": phase,
        "phaseDetail": (f"Fase estimada automaticamente pelo texto da notícia ({row.get('signal_type') or 'sinal'}). "
                        "Confirmar na fonte oficial antes de prospectar."),
        "executor": "Não identificado",
        "entry": ("Agora: identificar empreendedor, executor/EPC e comprador do pacote. "
                  "Execução: " + need[0].lower() + need[1:]),
        "need": need,
        "firstOutcome": FIRST_OUTCOME,
        "buyerTarget": BUYER_TARGET,
        "accounts": [],
        "companies": [],
        "bidStatus": BID_STATUS,
        "durationMethod": DURATION_METHOD,
        "steps": ["Ler a notícia original, identificar o empreendedor e localizar o canal oficial de fornecedores "
                  "ou de contato institucional; pedir encaminhamento a Suprimentos do projeto."] + STEPS_2_5,
        "stepTiming": STEP_TIMING,
        "trigger": "Confirmação do projeto, do executor/EPC e de pacote aberto para cotação.",
        "questions": questions_for(need),
        "message": message_for(row.get("title") or ""),
        "gaps": [
            "Empreendedor, executor/EPC e comprador do pacote ainda não pesquisados (ficha preliminar automática).",
            "Nome/e-mail direto do comprador do pacote não confirmado publicamente.",
            "Pedido aberto, orçamento disponível e janela de cotação precisam de confirmação com o contratante.",
        ],
        "followup": FOLLOWUP_ACTIVE if priority in ("Prospectar", "Preparar") else FOLLOWUP_MONITOR,
        "checked": (f"Ficha preliminar gerada automaticamente a partir da notícia coletada em {collected}. "
                    "Fase, contatos e empresas não foram verificados; funções de compra e ações são recomendações."),
        "sources": [],
    }


def ui_date(value) -> str:
    from .ui import fmt_date

    return fmt_date(value)


# ------------------------------------------------------------- leitura
def get_dossiers() -> dict[str, dict]:
    """{url_normalizada: ficha} das fichas pesquisadas gravadas no banco."""
    with db.connect() as conn:
        rows = conn.execute("SELECT news_url, data FROM dossiers").fetchall()
    return {r["news_url"]: json.loads(r["data"]) for r in rows}


def get_accounts() -> dict[str, dict]:
    with db.connect() as conn:
        rows = conn.execute("SELECT key, data FROM accounts").fetchall()
    return {r["key"]: json.loads(r["data"]) for r in rows}


def dossier_for(row: dict, researched: dict[str, dict]) -> dict:
    return researched.get(row.get("url")) or auto_dossier(row)


def as_text(row: dict, d: dict, accounts: dict) -> str:
    """Texto da ficha completa para copiar (mesma ordem do botão "Copiar ficha completa" da newsletter)."""
    def acc(k):
        a = accounts.get(k)
        if not a:
            return ""
        guide = "\n".join(f"{i}. {t}" for i, t in enumerate(a.get("guide") or [], 1))
        return (f"{a.get('name')} — {a.get('about')}\n{a.get('channel')}\n{a.get('kind')}\nFonte: {a.get('url')}\n"
                f"Cadastro: {a.get('portal') or 'Solicitar fluxo oficial'}\n{guide}")

    steps = []
    timing = d.get("stepTiming") or []
    for i, t in enumerate(d.get("steps") or [], 1):
        e = timing[i - 1] if i <= len(timing) else {}
        steps.append(f"{i}. {t}\nTrabalho interno: {e.get('internal', '—')}\nEspera externa: {e.get('external', '—')}\n"
                     f"Quando iniciar: {e.get('start', '—')}\nAvanço: {e.get('done', '—')}")
    parts = [
        row.get("title") or "",
        f"ENTRADA DA CORDEIRO: {d.get('priority')}",
        f"FASE: {d.get('phase')}", d.get("phaseDetail") or "",
        f"EXECUTOR: {d.get('executor')}",
        f"ENTRADA: {d.get('entry')}", f"SERVIÇO: {d.get('need')}", f"RESULTADO: {d.get('firstOutcome')}",
        f"QUEM PROCURAR: {d.get('buyerTarget')}",
        "CONTATOS E CADASTRO:", "\n\n".join(filter(None, (acc(k) for k in d.get("accounts") or []))) or
        "Canal específico ainda não localizado.",
        "EMPRESAS: " + ("\n".join(f"{c.get('name')} — {c.get('role')} — {c.get('status')}"
                                   for c in d.get("companies") or []) or "Não identificadas"),
        f"BASE DAS ESTIMATIVAS: {d.get('durationMethod')}",
        "PASSOS E PRAZOS:\n" + "\n\n".join(steps),
        f"CRITÉRIO PARA AVANÇAR: {d.get('trigger')}",
        "PERGUNTAS:\n" + "\n".join(d.get("questions") or []),
        f"MENSAGEM: {d.get('message')}",
        "LACUNAS:\n" + "\n".join(d.get("gaps") or []),
        f"ACOMPANHAMENTO: {d.get('followup')}",
        f"FONTE DA NOTÍCIA: {row.get('url')}",
        "FONTES ADICIONAIS: " + ("\n".join(f"{x.get('name')} {x.get('url')}" for x in d.get("sources") or []) or "—"),
    ]
    return "\n\n".join(p for p in parts if p)


# ------------------------------------------------------------- importação da newsletter
def _embedded_json(html: str, var: str):
    marker = f"window.{var}"
    start = html.find(marker)
    if start < 0:
        return None
    start = html.index("=", start) + 1
    while html[start] in " \t\r\n":
        start += 1
    return json.JSONDecoder().raw_decode(html[start:])[0]


DOSSIER_FIELDS = ("priority", "phase", "phaseDetail", "executor", "entry", "need", "firstOutcome", "buyerTarget",
                  "accounts", "companies", "bidStatus", "durationMethod", "steps", "stepTiming", "trigger",
                  "questions", "message", "gaps", "followup", "checked", "sources", "client", "action", "next", "days")


def import_newsletter(html: str) -> dict:
    """Importa notícias, fichas e contas do HTML da newsletter. A classificação do analista prevalece."""
    db.init_db()
    docs = _embedded_json(html, "__SNAPSHOT_DOCS__")
    if not docs:
        raise ValueError("O arquivo não contém a base da newsletter (window.__SNAPSHOT_DOCS__).")
    accounts = _embedded_json(html, "__CORDEIRO_ACCOUNTS__") or {}
    now = config.now().isoformat(timespec="seconds")
    stats = {"noticias_novas": 0, "noticias_atualizadas": 0, "fichas": 0, "contas": len(accounts)}

    with db.connect() as conn:
        for key, acc in accounts.items():
            conn.execute("INSERT INTO accounts(key, data, updated_at) VALUES (?,?,?) "
                         "ON CONFLICT(key) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                         (key, json.dumps(acc, ensure_ascii=False), now))

    for d in docs:
        if not d.get("url"):
            continue
        url = engines.normalize_url(d["url"])
        captured = d.get("date_captured") or config.today().isoformat()
        uf = d.get("uf") or []
        item = {
            "url": url, "title": d.get("title") or url, "source": d.get("source"),
            "published_at": d.get("date_published"), "summary": d.get("summary"),
            "term": "Newsletter Radar Cordeiro", "theme": d.get("category"), "engine": "newsletter",
            "collected_at": f"{captured}T08:00:00", "collected_day": captured, "run_id": None,
            "category": d.get("category"), "vertical": d.get("vertical"),
            "ufs": ",".join(uf if isinstance(uf, list) else [uf]), "potential": d.get("potential"),
            "demand": d.get("demand"), "prazo": d.get("prazo"), "signal_type": d.get("signal_type"),
            "impacto": d.get("impacto"),
        }
        if db.insert_news(item):
            stats["noticias_novas"] += 1
        else:
            stats["noticias_atualizadas"] += 1
        manual = ("category", "vertical", "ufs", "potential", "demand", "prazo", "signal_type", "impacto")
        with db.connect() as conn:
            conn.execute(f"UPDATE news SET {', '.join(f + '=?' for f in manual)}, manual_class=1 WHERE url=?",
                         (*(item[f] for f in manual), url))
            if d.get("phase"):
                ficha = {k: d.get(k) for k in DOSSIER_FIELDS} | {"origin": "newsletter", "newsletter_id": d.get("id")}
                conn.execute("INSERT INTO dossiers(news_url, data, origin, updated_at) VALUES (?,?,?,?) "
                             "ON CONFLICT(news_url) DO UPDATE SET data=excluded.data, origin=excluded.origin, "
                             "updated_at=excluded.updated_at",
                             (url, json.dumps(ficha, ensure_ascii=False), "newsletter", now))
                stats["fichas"] += 1
    return stats


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else config.BASE_DIR / "radar-cordeiro-relatorio-NEWSLETTER-integrado.html")
    print(import_newsletter(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
