"""Notícias repetidas: a mesma matéria publicada por vários sites (URLs diferentes, título igual ou quase).

A deduplicação por URL já evita gravar o mesmo link duas vezes; aqui juntamos links diferentes da
mesma notícia. Cada grupo mantém uma notícia principal (visível) e marca as demais com
duplicate_of = id da principal (ficam no banco, ocultas no painel e no Modo TV).

Regra (só entre notícias com relação com a Cordeiro, publicadas/coletadas com até 30 dias de diferença):
  * títulos quase idênticos (semelhança >= 0.90), ou
  * títulos muito parecidos (>= 60% das palavras e pelo menos 5 em comum)
  e, nos dois casos, sem números conflitantes: um título pode ter um número a mais, mas "R$ 20 bi" x
  "R$ 18 bi" não se juntam ("em SC" x "em SP" também não, por terem poucas palavras em comum).
"""
from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher

from . import db
from .classify import has_relation, norm

WINDOW_DAYS = 30  # republicações semanas depois ainda contam como a mesma notícia
STOP = set("a o os as de da do das dos e em no na nos nas para por com um uma que se ao a e sobre apos ate mais "
           "seu sua seus suas pelo pela pelos pelas como entre".split())
ENGINE_RANK = {"manual": 0, "newsletter": 0, "exa": 1, "firecrawl": 2, "duckduckgo": 3}


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


def _day(row) -> date | None:
    value = str(row.get("published_at") or row.get("collected_at") or "")[:10]
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def same_story(a: dict, b: dict) -> bool:
    fa, fb = a["f"], b["f"]
    if not fa["tokens"] or not fb["tokens"]:
        return False
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
    if jac < 0.35:  # atalho: nem vale comparar o texto
        return False
    return SequenceMatcher(None, fa["text"], fb["text"]).ratio() >= 0.90


def _primary(group: list[dict]) -> dict:
    return min(group, key=lambda r: (-(r.get("manual_class") or 0), ENGINE_RANK.get(r.get("engine"), 9), r["id"]))


def run_all() -> dict:
    """Recalcula os grupos de repetidas entre as notícias com relação com a Cordeiro."""
    db.init_db()
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, title, engine, published_at, collected_at, demand, COALESCE(manual_class, 0) AS manual_class, "
            "duplicate_of FROM news").fetchall()]
    rows = [r for r in rows if has_relation(r.get("demand"))]
    for r in rows:
        r["f"], r["day"] = _features(r["title"]), _day(r)

    parent = {r["id"]: r["id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_id = {r["id"]: r for r in rows}
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if find(a["id"]) != find(b["id"]) and same_story(a, b):
                parent[find(b["id"])] = find(a["id"])

    groups: dict[int, list[dict]] = {}
    for r in rows:
        groups.setdefault(find(r["id"]), []).append(r)
    target = {}
    for group in groups.values():
        main = _primary(group)
        for r in group:
            target[r["id"]] = None if r["id"] == main["id"] else main["id"]

    changed = 0
    with db.connect() as conn:
        for nid, dup in target.items():
            if by_id[nid].get("duplicate_of") != dup:
                conn.execute("UPDATE news SET duplicate_of=? WHERE id=?", (dup, nid))
                changed += 1
    n_dups = sum(1 for v in target.values() if v)
    return {"grupos": sum(1 for g in groups.values() if len(g) > 1), "repetidas": n_dups, "alteradas": changed}
