"""Rotina de coleta: busca no Exa (máx. 5/dia) e no DuckDuckGo, classifica e grava no SQLite.

Uso pela linha de comando:
    python -m radar.collector            # execução manual
    python -m radar.collector --agendado # como o scheduler chama
"""
from __future__ import annotations

import argparse
import logging
import time
import traceback
from logging.handlers import RotatingFileHandler

from . import classify, config, db, engines, images

log = logging.getLogger("radar")


def setup_logging() -> None:
    if log.handlers:
        return
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = RotatingFileHandler(config.LOG_DIR / "coleta.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    log.setLevel(logging.INFO)


def select_exa_terms(terms: list[dict], remaining: int, day_ordinal: int) -> list[dict]:
    """Escolhe até `remaining` termos para o Exa. Usa os marcados com exa=true (por prioridade);
    se houver mais termos que cota, faz rodízio diário para cobrir todos ao longo dos dias."""
    if remaining <= 0:
        return []
    pool = [t for t in terms if t["exa"]] or list(terms)
    pool.sort(key=lambda t: t["prioridade"])
    if len(pool) <= remaining:
        return pool
    offset = (day_ordinal * remaining) % len(pool)
    rotated = pool[offset:] + pool[:offset]
    return rotated[:remaining]


def _store_results(results, term, engine, run_id, cfg, image_jobs: list) -> int:
    new = 0
    for r in results:
        if classify.is_excluded(r["title"], r["summary"], cfg):
            continue
        ts = config.now()
        item = {
            **r,
            "url": engines.normalize_url(r["url"]),
            "term": term["texto"],
            "theme": term["tema"],
            "engine": engine,
            "collected_at": ts.isoformat(timespec="seconds"),
            "collected_day": ts.date().isoformat(),
            "run_id": run_id,
            **classify.classify(r["title"], r["summary"], term["tema"], cfg),
        }
        if db.insert_news(item):
            new += 1
            image_jobs.append((db.news_id(item["url"]), item["url"], [r.get("image")]))
    return new


def run_collection(trigger: str = "manual", progress=None) -> dict:
    """Executa uma coleta completa. `progress(fração, mensagem)` é opcional (usado pelo Streamlit)."""
    setup_logging()
    db.init_db()
    cfg = config.load_config()
    say = progress or (lambda frac, msg: None)

    running = db.active_run()
    if running:
        msg = f"Já existe uma coleta em andamento (execução #{running['id']}, iniciada {running['started_at']})."
        log.warning(msg)
        return {"status": "ignorada", "message": msg}

    run_id = db.start_run(trigger)
    day = config.today()
    day_key = day.isoformat()
    exa_limit = cfg["exa"]["limite_diario"]
    terms = list(config.iter_terms(cfg))
    stats = {"n_searches": 0, "n_results": 0, "n_new": 0, "n_errors": 0, "exa_used": 0}
    image_jobs: list[tuple[int, str, list[str]]] = []  # notícias novas que receberão imagens no fim
    log.info("Coleta #%s (%s) iniciada com %d termos.", run_id, trigger, len(terms))

    def fail(engine, term, exc):
        stats["n_errors"] += 1
        msg = f"{type(exc).__name__}: {exc}"
        log.error("[%s] '%s' falhou: %s", engine, term, msg)
        db.log_error(run_id, msg, engine=engine, term=term, details=traceback.format_exc())
        return msg

    try:
        # ---------------- Exa: limite rígido diário, reservado no banco antes de cada chamada
        api_key = config.exa_api_key()
        remaining = max(0, exa_limit - db.exa_used(day_key))
        exa_terms = select_exa_terms(terms, remaining, day.toordinal()) if api_key else []
        if not api_key:
            fail("exa", "-", RuntimeError("EXA_API_KEY não configurada no .env — buscas Exa ignoradas."))
        elif remaining == 0:
            log.info("Cota diária do Exa já utilizada (%d/%d).", exa_limit, exa_limit)

        total_steps = len(exa_terms) + len(terms) or 1
        step = 0
        for term in exa_terms:
            step += 1
            say(step / total_steps, f"Exa: {term['texto']}")
            if not db.reserve_exa_call(day_key, exa_limit):
                log.info("Limite do Exa atingido durante a execução.")
                break
            stats["exa_used"] += 1
            stats["n_searches"] += 1
            try:
                results = engines.search_exa(term["texto"], api_key, cfg)
                new = _store_results(results, term, "exa", run_id, cfg, image_jobs)
                stats["n_results"] += len(results)
                stats["n_new"] += new
                db.log_search(run_id, "exa", term["texto"], term["tema"], len(results), new)
            except Exception as exc:
                db.log_search(run_id, "exa", term["texto"], term["tema"], status="erro",
                              error=fail("exa", term["texto"], exc))

        # ---------------- DuckDuckGo: todos os termos ativos
        pause = float(cfg["ddg"].get("pausa_segundos", 2))
        for i, term in enumerate(terms):
            step += 1
            say(step / total_steps, f"DuckDuckGo: {term['texto']}")
            if i:
                time.sleep(pause)
            stats["n_searches"] += 1
            try:
                results = engines.search_ddg(term["texto"], cfg)
                new = _store_results(results, term, "duckduckgo", run_id, cfg, image_jobs)
                stats["n_results"] += len(results)
                stats["n_new"] += new
                db.log_search(run_id, "duckduckgo", term["texto"], term["tema"], len(results), new)
            except Exception as exc:
                db.log_search(run_id, "duckduckgo", term["texto"], term["tema"], status="erro",
                              error=fail("duckduckgo", term["texto"], exc))

        # ---------------- Imagens (até 2 por notícia nova), em paralelo no fim da coleta
        n_images = 0
        if image_jobs:
            say(0.99, f"Baixando imagens de {len(image_jobs)} notícias novas…")
            n_images = images.store_many(image_jobs)

        status = "ok" if stats["n_errors"] == 0 else "com_erros"
        message = f"{stats['n_new']} notícias novas de {stats['n_results']} resultados; {n_images} imagens salvas."
    except Exception as exc:  # erro inesperado fora de uma busca específica
        fail("coleta", "-", exc)
        status, message = "falhou", f"Falha geral: {exc}"

    db.finish_run(run_id, status, message, **stats)
    say(1.0, "Concluído")
    log.info("Coleta #%s finalizada (%s): %s Exa usado: %d.", run_id, status, message, stats["exa_used"])
    return {"run_id": run_id, "status": status, "message": message, **stats}


def reclassify_all() -> int:
    """Reaplica as regras de classificação a toda a base (após ajustar classify.py ou o termos.yaml)."""
    db.init_db()
    cfg = config.load_config()
    fields = ("category", "vertical", "ufs", "potential", "demand", "prazo", "signal_type", "impacto")
    with db.connect() as conn:
        # Notícias classificadas pelo analista (importadas da newsletter) não são sobrescritas.
        rows = conn.execute("SELECT id, title, summary, theme FROM news WHERE COALESCE(manual_class, 0) = 0").fetchall()
        for r in rows:
            c = classify.classify(r["title"], r["summary"], r["theme"], cfg)
            conn.execute(f"UPDATE news SET {', '.join(f + '=?' for f in fields)} WHERE id=?",
                         (*(c[f] for f in fields), r["id"]))
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Coleta de notícias do Radar Cordeiro")
    parser.add_argument("--agendado", action="store_true", help="marca a execução como agendada")
    parser.add_argument("--reclassificar", action="store_true", help="só reaplica a classificação à base existente")
    args = parser.parse_args()
    if args.reclassificar:
        print(f"{reclassify_all()} notícias reclassificadas.")
        return
    result = run_collection("agendado" if args.agendado else "manual")
    print(result)


if __name__ == "__main__":
    main()
