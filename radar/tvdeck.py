"""Dados do Modo TV: capa com indicadores + um slide por notícia da base."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from . import config, db, dossier, images, score
from .classify import has_relation
from .ui import NOTA_COLORS, POTENTIALS, UF_LABEL, VERT_COLORS, fmt_date
from .ui import im_code as ui_im_code

POT_COLORS = {"Muito Alto": "#a34a12", "Alto": "#c9761a", "Médio": "#a1441f", "Baixo": "#7c8b86"}
NEW_DAYS = 7


def _trim(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def build_deck(max_ops: int | None = None) -> dict:
    """Capa + todas as notícias da base (ou as `max_ops` primeiras), na ordem de prioridade."""
    db.init_db()
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM news").fetchall()]
        # sem relação com a Cordeiro e repetidas (mesma notícia em outro site): fora da TV
        rows = [r for r in rows if has_relation(r.get("demand")) and r.get("duplicate_of") is None]
        last = conn.execute("SELECT finished_at FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    new_since = (config.today() - timedelta(days=NEW_DAYS)).isoformat()
    researched = dossier.get_dossiers()
    cfg = config.load_config()
    weights = score.weights(cfg)
    for r in rows:
        r["is_new"] = r["collected_day"] >= new_since
        r["uf_list"] = [u for u in (r.get("ufs") or "").split(",") if u]
        r["ficha"] = dossier.dossier_for(r, researched)
        r["score"] = score.score(r, r["ficha"], cfg, weights)  # nota 0–10, como no painel

    # Capa
    ufs = Counter(u for r in rows for u in r["uf_list"] if u not in ("BR", "NE"))
    cover = {
        "total": len(rows),
        "high": sum(r["potential"] in ("Muito Alto", "Alto") for r in rows),
        "new": sum(r["is_new"] for r in rows),
        "updated": fmt_date(last["finished_at"]) if last else "—",
        "by_potential": [[p, sum(r["potential"] == p for r in rows), POT_COLORS[p]] for p in POTENTIALS],
        "by_nota": [[f, sum(r["score"]["faixa"] == f for r in rows), c] for f, c in NOTA_COLORS.items()],
        "by_vertical": [[v, sum(r["vertical"] == v for r in rows), c] for v, c in VERT_COLORS.items()],
        "by_uf": [[UF_LABEL.get(u, u), n, "#3f8f8a"] for u, n in ufs.most_common(4)],
    }

    # Todas as notícias: novas da semana primeiro, depois pela nota (maior → menor) e data.
    picked = list(rows)
    picked.sort(key=lambda r: r.get("published_at") or r["collected_at"], reverse=True)
    picked.sort(key=lambda r: (not r["is_new"], -r["score"]["nota"]))
    if max_ops:
        picked = picked[:max_ops]

    imgs = images.images_by_news()
    slides = []
    for r in picked:
        f, s = r["ficha"], r["score"]
        slides.append({
            "title": r["title"],
            "im": ui_im_code(r),
            "summary": _trim(r.get("summary"), 520),
            "impacto": _trim(r.get("impacto"), 420),
            "demand": r.get("demand") or "",
            "potential": r.get("potential") or "—",
            "vertical": r.get("vertical") or "",
            "vertColor": VERT_COLORS.get(r.get("vertical"), "#4a6a86"),
            "category": r.get("category") or "",
            "ufs": [UF_LABEL.get(u, u) for u in r["uf_list"]],
            "source": r.get("source") or "",
            "date": fmt_date(r.get("published_at") or r["collected_at"]),
            "signal": r.get("signal_type") or "",
            "isNew": r["is_new"],
            "images": imgs.get(r["id"], [])[: images.MAX_IMAGES],
            "entrada": f.get("priority") or "",
            "fase": f.get("phase") or "",
            "executor": f.get("executor") or "",
            "fichaOrigem": f.get("origin"),
            "nota": f"{s['nota']:.1f}".replace(".", ","),
            "faixa": s["faixa"],
            "notaColor": NOTA_COLORS.get(s["faixa"], "#7c8b86"),
            "motivos": s["motivos"],
        })
    return {"cover": cover, "slides": slides, "generatedAt": config.now().isoformat(timespec="seconds")}
