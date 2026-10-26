"""Notícias repetidas: a mesma matéria publicada por vários sites (URLs diferentes, título igual ou quase).

A deduplicação por URL já evita gravar o mesmo link duas vezes; aqui juntamos links diferentes da
mesma notícia. Cada grupo mantém uma notícia principal (visível) e marca as demais com
duplicate_of = id da principal (ficam no banco, ocultas no painel e no Modo TV).

Regra (só entre notícias com relação com a Cordeiro, publicadas/coletadas com até 30 dias de diferença),
pelo título OU pelo conteúdo (título + resumo, ponderado por TF-IDF: palavras raras pesam mais):
  * títulos quase idênticos (semelhança >= 0.90), ou
  * títulos muito parecidos (>= 60% das palavras e pelo menos 5 em comum), ou
  * conteúdo parecido (cosseno >= 0.50), ou
  * conteúdo razoavelmente parecido (>= 0.42) e títulos com 2+ palavras raras em comum (>= 3 se < 0.45)
    — pega a mesma notícia escrita de outro jeito ("biocarvão de coco" x "carvão de casca de coco")
  e, nos dois casos, sem números conflitantes: um título pode ter um número a mais, mas "R$ 20 bi" x
  "R$ 18 bi" não se juntam ("em SC" x "em SP" também não, por terem poucas palavras em comum).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date
from difflib import SequenceMatcher

from . import db
from .classify import has_relation, norm

WINDOW_DAYS = 30  # republicações semanas depois ainda contam como a mesma notícia
STOP = set("a o os as de da do das dos e em no na nos nas para por com um uma que se ao a e sobre apos ate mais "
           "seu sua seus suas pelo pela pelos pelas como entre".split())
# Verbos e palavras genéricas de manchete: não identificam a notícia.
GENERIC = set("faz fazer feito chega chegam geram gera recebe recebem preve preveem lanca lancam anuncia anunciam "
              "define destaca vincula apresenta acompanha rebate defende diz afirma aponta mostra ganha ganham "
              "realiza realizam inicia iniciam comeca comecam primeira primeiro novo nova novos novas mais anos".split())
COS_STRONG, COS_RARE, COS_RARE2 = 0.50, 0.42, 0.45


def clean_title(title: str) -> str:
    """Título sem o nome do site/colunista no fim ("… - Diário do Nordeste", "… | Rumbo Comex")."""
    parts = re.split(r"\s+[-|–]\s+", title or "")
    if len(parts) > 1 and len(parts[0].split()) >= 4:
        return parts[0]
    return title or ""


def _features(title: str) -> dict:
    t = norm(clean_title(title)).strip()
    words = re.findall(r"[a-z0-9]+", t)
    return {
        "text": t,
        "tokens": {w for w in words if w not in STOP and len(w) > 2},
        "numbers": {n.replace(".", "").replace(",", "") for n in re.findall(r"\d+(?:[.,]\d+)?", t)},
    }


def _stems(text: str) -> list[str]:
    return [w[:6] for w in re.findall(r"[a-z0-9]+", norm(text or ""))
            if w not in STOP and w not in GENERIC and len(w) > 2 and not w.isdigit()]


def _ufs(row) -> set[str]:
    return {u for u in str(row.get("ufs") or "").split(",") if u and u not in ("BR", "NE")}


def _day(row) -> date | None:
    value = str(row.get("published_at") or row.get("collected_at") or "")[:10]
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def same_story(a: dict, b: dict, ctx: dict | None = None) -> bool:
    """ctx (de run_all): vetores TF-IDF e idf, para comparar também o conteúdo."""
    fa, fb = a["f"], b["f"]
    if not fa["tokens"] or not fb["tokens"]:
        return False
    ua, ub = _ufs(a), _ufs(b)
    if ua and ub and not (ua & ub):
        return False  # estados diferentes ("Licitações abertas em PE" x "em SP")
    na, nb = fa["numbers"], fb["numbers"]
    if na and nb and not (na <= nb or nb <= na):
        return False  # números que não batem: notícias diferentes ("R$ 20 bi" x "R$ 18 bi")
    da, dbb = a["day"], b["day"]
    if da and dbb and abs((da - dbb).days) > WINDOW_DAYS:
        return False
    common = len(fa["tokens"] & fb["tokens"])
    jac = common / len(fa["tokens"] | fb["tokens"])
    if jac >= 0.6 and common >= 5:
        return True
    if jac >= 0.35 and SequenceMatcher(None, fa["text"], fb["text"]).ratio() >= 0.90:
        return True
    if not ctx:
        return False
    va, vb = ctx["vec"][a["id"]], ctx["vec"][b["id"]]
    if len(va) > len(vb):
        va, vb = vb, va
    cos = sum(x * vb.get(tok, 0.0) for tok, x in va.items())
    if cos >= COS_STRONG:
        return True
    if cos >= COS_RARE:
        rare = [tok for tok in a["stems_title"] & b["stems_title"] if ctx["idf"].get(tok, 0) >= ctx["rare"]]
        return len(rare) >= 3 or (len(rare) >= 2 and cos >= COS_RARE2)
    return False


def _primary(group: list[dict]) -> dict:
    """Fica visível: ficha pesquisada/incluída à mão; senão a mais recente (informação mais atual)."""
    def recency(r):
        return str(r.get("published_at") or r.get("collected_at") or "")
    return max(group, key=lambda r: ((r.get("manual_class") or 0), recency(r), r["id"]))


def run_all(dry_run: bool = False) -> dict:
    """Recalcula os grupos de repetidas entre as notícias com relação com a Cordeiro.
    dry_run=True: não grava; devolve os grupos para revisão em "grupos_detalhe"."""
    db.init_db()
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, title, summary, ufs, engine, published_at, collected_at, demand, "
            "COALESCE(manual_class, 0) AS manual_class, duplicate_of, duplicate_manual FROM news").fetchall()]
    rows = [r for r in rows if has_relation(r.get("demand"))]
    for r in rows:
        r["f"], r["day"] = _features(r["title"]), _day(r)
        title_stems = _stems(clean_title(r["title"]))
        r["stems_title"] = set(title_stems)
        r["bag"] = Counter(title_stems * 2 + _stems(r.get("summary")))  # título pesa o dobro

    # TF-IDF sobre título + resumo: palavras raras ("Diamante", "coco") pesam mais que comuns ("energia")
    n_docs = max(1, len(rows))
    dfreq = Counter(tok for r in rows for tok in r["bag"])
    idf = {tok: math.log(n_docs / n) for tok, n in dfreq.items()}
    vec = {}
    for r in rows:
        v = {tok: tf * idf[tok] for tok, tf in r["bag"].items()}
        size = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vec[r["id"]] = {tok: x / size for tok, x in v.items()}
    ctx = {"vec": vec, "idf": idf, "rare": math.log(n_docs / 10)}  # rara: aparece em até ~10 notícias

    parent = {r["id"]: r["id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_id = {r["id"]: r for r in rows}
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if find(a["id"]) != find(b["id"]) and same_story(a, b, ctx):
                parent[find(b["id"])] = find(a["id"])

    groups: dict[int, list[dict]] = {}
    for r in rows:
        groups.setdefault(find(r["id"]), []).append(r)
    target = {}
    for group in groups.values():
        main = _primary(group)
        for r in group:
            target[r["id"]] = None if r["id"] == main["id"] else main["id"]
    # Marcações manuais prevalecem (casos que a regra não pega sem arriscar juntar notícias diferentes)
    for r in rows:
        if r.get("duplicate_manual") and r["duplicate_manual"] in by_id:
            target[r["id"]] = by_id[r["duplicate_manual"]].get("duplicate_of") or r["duplicate_manual"]

    if dry_run:
        detail = []
        for group in groups.values():
            if len(group) > 1:
                main = _primary(group)
                detail.append({"principal": (main["id"], main["title"]),
                               "copias": [(r["id"], r["title"]) for r in group if r["id"] != main["id"]]})
        return {"grupos": len(detail), "repetidas": sum(len(d["copias"]) for d in detail), "grupos_detalhe": detail}

    changed = 0
    with db.connect() as conn:
        for nid, dup in target.items():
            if by_id[nid].get("duplicate_of") != dup:
                conn.execute("UPDATE news SET duplicate_of=? WHERE id=?", (dup, nid))
                changed += 1
    n_dups = sum(1 for v in target.values() if v)
    return {"grupos": sum(1 for g in groups.values() if len(g) > 1), "repetidas": n_dups, "alteradas": changed}


def mark_manual(copy_id: int, main_id: int) -> dict:
    """Marca à mão a notícia copy_id como repetida de main_id (ou desfaz, com main_id=0) e reagrupa."""
    with db.connect() as conn:
        conn.execute("UPDATE news SET duplicate_manual=? WHERE id=?", (main_id or None, copy_id))
    return run_all()


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 4 and sys.argv[1] == "--juntar":
        print(mark_manual(int(sys.argv[2]), int(sys.argv[3])))   # python -m radar.dedupe --juntar <copia> <principal>
    elif len(sys.argv) == 3 and sys.argv[1] == "--separar":
        print(mark_manual(int(sys.argv[2]), 0))                   # python -m radar.dedupe --separar <id>
    else:
        print(run_all())
