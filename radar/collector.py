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

from . import classify, config, db, dedupe, engines, images

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


def select_exa_terms(terms: list[dict], remaining: int, day_ordinal: int, flag: str = "exa") -> list[dict]:
    """Escolhe até `remaining` termos para o Exa. Usa os marcados com exa=true (por prioridade);
    se houver mais termos que cota, faz rodízio diário para cobrir todos ao longo dos dias."""
    if remaining <= 0:
        return []
    pool = [t for t in terms if t.get(flag)] or list(terms)
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
            **classify.classify(r["title"], r["summary"], term["tema"], cfg, url=r["url"]),
        }
        if db.insert_news(item):
            new += 1
            if classify.has_relation(item.get("demand")):  # sem relação com a Cordeiro: não precisa de imagem
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
    stats = {"n_searches": 0, "n_results": 0, "n_new": 0, "n_errors": 0, "exa_used": 0, "firecrawl_used": 0}
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

        # Firecrawl: limite diário configurável (cada busca consome créditos), reservado antes da chamada
        fc_cfg = cfg["firecrawl"]
        fc_key = config.firecrawl_api_key() if fc_cfg.get("ativo", True) else None
        fc_limit = int(fc_cfg.get("limite_diario", 10))
        fc_remaining = max(0, fc_limit - db.api_used("firecrawl", day_key)["used"])
        fc_terms = select_exa_terms(terms, fc_remaining, day.toordinal(), flag="firecrawl") if fc_key else []

        total_steps = len(exa_terms) + len(fc_terms) + len(terms) or 1
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

        # ---------------- Firecrawl (notícias, Brasil)
        for term in fc_terms:
            step += 1
            say(step / total_steps, f"Firecrawl: {term['texto']}")
            if not db.reserve_api_call("firecrawl", day_key, fc_limit):
                log.info("Limite diário do Firecrawl atingido durante a execução.")
                break
            stats["firecrawl_used"] += 1
            stats["n_searches"] += 1
            try:
                results, credits = engines.search_firecrawl(term["texto"], fc_key, cfg)
                db.add_api_credits("firecrawl", day_key, credits)
                new = _store_results(results, term, "firecrawl", run_id, cfg, image_jobs)
                stats["n_results"] += len(results)
                stats["n_new"] += new
                db.log_search(run_id, "firecrawl", term["texto"], term["tema"], len(results), new)
            except Exception as exc:
                db.log_search(run_id, "firecrawl", term["texto"], term["tema"], status="erro",
                              error=fail("firecrawl", term["texto"], exc))

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

        # ---------------- Repetidas: agrupa a mesma notícia publicada por vários sites
        try:
            dd = dedupe.run_all()
            log.info("Repetidas: %(repetidas)s notícias em %(grupos)s grupos.", dd)
        except Exception as exc:  # não derruba a coleta
            fail("dedupe", "-", exc)
        with db.connect() as conn:
            dups = {r["id"] for r in conn.execute("SELECT id FROM news WHERE duplicate_of IS NOT NULL")}
        image_jobs = [j for j in image_jobs if j[0] not in dups]  # cópia não precisa de imagem

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
    log.info("Coleta #%s finalizada (%s): %s Exa: %d, Firecrawl: %d.", run_id, status, message,
             stats["exa_used"], stats["firecrawl_used"])
    return {"run_id": run_id, "status": status, "message": message, **stats}


def reclassify_all() -> int:
    """Reaplica as regras de classificação a toda a base (após ajustar classify.py ou o termos.yaml)."""
    db.init_db()
    cfg = config.load_config()
    fields = ("category", "vertical", "ufs", "potential", "demand", "prazo", "signal_type", "impacto")
    with db.connect() as conn:
        # Notícias classificadas pelo analista (importadas da newsletter) não são sobrescritas.
        rows = conn.execute(
            "SELECT id, url, title, summary, theme FROM news WHERE COALESCE(manual_class, 0) = 0").fetchall()
        for r in rows:
            c = classify.classify(r["title"], r["summary"], r["theme"], cfg, url=r["url"])
            conn.execute(f"UPDATE news SET {', '.join(f + '=?' for f in fields)} WHERE id=?",
                         (*(c[f] for f in fields), r["id"]))
    return len(rows)


def add_from_url(url: str, theme: str | None = None) -> dict:
    """Inclui manualmente uma notícia a partir do link (ex.: matéria recebida por WhatsApp).

    Lê título, resumo e data da própria página, classifica com as mesmas regras da coleta, grava
    (sem duplicar, pela URL) e baixa até 2 imagens. Retorna {"ok", "nova", "id", "title", "message"}.
    """
    import re
    from html import unescape

    import requests

    db.init_db()
    norm_url = engines.normalize_url(url)
    if existing := db.news_id(norm_url):
        return {"ok": True, "nova": False, "id": existing, "message": "Esta notícia já está no painel."}
    try:
        resp = requests.get(url, headers=images.HEADERS, timeout=25)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return {"ok": False, "nova": False, "message": f"Não foi possível abrir o link: {exc}"}
    html = resp.text

    def meta(*names):
        for n in names:
            pat = re.escape(n)
            m = (re.search(rf'<meta[^>]+(?:property|name)=["\']{pat}["\'][^>]*content=["\']([^"\']+)', html, re.I)
                 or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{pat}["\']', html, re.I))
            if m:
                return unescape(m.group(1)).strip()
        return None

    site = meta("og:site_name") or engines.source_from_url(norm_url)
    title = meta("og:title", "twitter:title") or (re.search(r"<title>(.*?)</title>", html, re.S | re.I) or [None, url])[1]
    title = re.sub(r"\s+", " ", unescape(title)).strip()
    # tira o nome do site/colunista do fim do título ("… - Egídio Serpa - Diário do Nordeste")
    parts = [p.strip() for p in re.split(r"\s+[-|–]\s+", title)]
    if len(parts) > 1 and site and parts[-1].lower() == site.lower():
        title = parts[0]
    description = meta("og:description", "description", "twitter:description") or ""
    # texto da matéria a partir do resumo, para um resumo mais completo e uma classificação melhor
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html))))
    start = text.find(description[:60]) if description else -1
    body = text[start:start + 3000] if start >= 0 else description  # mais texto: valores e fase da obra
    summary = engines._clean(body or description, 520)
    published = engines.to_local_iso(meta("article:published_time", "og:published_time", "datePublished")
                                     or (re.search(r'"datePublished"\s*:\s*"([^"]+)"', html) or [None, None])[1])

    cfg = config.load_config()
    ts = config.now()
    item = {
        "url": norm_url, "title": title[:300], "source": engines.source_from_url(norm_url) if site is None else site,
        "published_at": published, "summary": summary, "term": "Inclusão manual", "theme": theme,
        "engine": "manual", "collected_at": ts.isoformat(timespec="seconds"), "collected_day": ts.date().isoformat(),
        "run_id": None, **classify.classify(title, body or summary, theme, cfg, url=norm_url),
    }
    db.insert_news(item)
    news_id = db.news_id(norm_url)
    with db.connect() as conn:  # classificada com o texto completo: reclassificações não sobrescrevem
        conn.execute("UPDATE news SET manual_class=1 WHERE id=?", (news_id,))
    dedupe.run_all()  # a incluída manualmente vira a principal se já houver a mesma notícia de outro site
    n_img = images.store_images(news_id, url, [meta("og:image")]) if classify.has_relation(item["demand"]) else 0
    log.info("Notícia incluída manualmente: #%s %s (%s imagens)", news_id, title, n_img)
    return {"ok": True, "nova": True, "id": news_id, "title": title, "images": n_img,
            "potential": item["potential"], "demand": item["demand"], "category": item["category"],
            "message": f"Notícia incluída: {title}"}


def update_obras(origem: str = "agendado") -> None:
    """Junto com a coleta: importa o Mapa de Obras mais recente de OBRAS_PASTA, se o arquivo mudou."""
    from . import obras

    try:
        res = obras.auto_import(origem)
    except Exception as exc:  # a coleta de notícias não deve falhar por causa das obras
        log.exception("Erro ao importar o Mapa de Obras")
        db.log_error(None, f"Obras: {exc}", engine="obras", details=traceback.format_exc())
        return
    if res and not res.get("sem_mudanca"):
        log.info("Mapa de Obras: %(total)s obras (%(novas)s novas, %(atualizadas)s atualizadas, "
                 "%(removidas)s removidas)", res)


def main() -> None:
    parser = argparse.ArgumentParser(description="Coleta de notícias do Radar Cordeiro")
    parser.add_argument("--agendado", action="store_true", help="marca a execução como agendada")
    parser.add_argument("--reclassificar", action="store_true", help="só reaplica a classificação à base existente")
    args = parser.parse_args()
    if args.reclassificar:
        print(f"{reclassify_all()} notícias reclassificadas.")
        return
    result = run_collection("agendado" if args.agendado else "manual")
    update_obras("agendado" if args.agendado else "manual")
    print(result)


if __name__ == "__main__":
    main()
