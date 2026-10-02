"""Acesso ao SQLite: execuções, buscas, notícias, uso do Exa e log de erros."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import timedelta

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger       TEXT NOT NULL,                 -- agendado | manual
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL,                 -- executando | ok | com_erros | falhou | ignorada
    n_searches    INTEGER DEFAULT 0,
    n_results     INTEGER DEFAULT 0,
    n_new         INTEGER DEFAULT 0,
    n_errors      INTEGER DEFAULT 0,
    exa_used      INTEGER DEFAULT 0,
    message       TEXT
);

CREATE TABLE IF NOT EXISTS searches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER REFERENCES runs(id),
    engine        TEXT NOT NULL,                 -- exa | duckduckgo
    term          TEXT NOT NULL,
    theme         TEXT,
    executed_at   TEXT NOT NULL,
    n_results     INTEGER DEFAULT 0,
    n_new         INTEGER DEFAULT 0,
    status        TEXT NOT NULL,                 -- ok | erro
    error         TEXT
);

CREATE TABLE IF NOT EXISTS news (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL UNIQUE,          -- URL normalizada (sem utm/fragmento)
    title         TEXT NOT NULL,
    source        TEXT,
    published_at  TEXT,                          -- ISO no fuso America/Fortaleza
    summary       TEXT,
    term          TEXT,                          -- termo que encontrou a notícia pela primeira vez
    theme         TEXT,                          -- tema do termo de busca
    engine        TEXT,                          -- mecanismo que encontrou primeiro
    collected_at  TEXT NOT NULL,
    collected_day TEXT NOT NULL,                 -- YYYY-MM-DD (fuso local)
    run_id        INTEGER REFERENCES runs(id),
    last_seen_at  TEXT,
    times_seen    INTEGER DEFAULT 1,
    category      TEXT,
    vertical      TEXT,
    ufs           TEXT,                          -- siglas separadas por vírgula
    potential     TEXT,
    demand        TEXT,
    prazo         TEXT,
    signal_type   TEXT,
    impacto       TEXT
);
CREATE INDEX IF NOT EXISTS ix_news_day ON news(collected_day);
CREATE INDEX IF NOT EXISTS ix_news_pub ON news(published_at);

CREATE TABLE IF NOT EXISTS exa_usage (
    day           TEXT PRIMARY KEY,              -- YYYY-MM-DD (fuso local)
    used          INTEGER NOT NULL DEFAULT 0
);

-- Ficha do executivo pesquisada (importada da newsletter), ligada à notícia pela URL normalizada.
CREATE TABLE IF NOT EXISTS dossiers (
    news_url      TEXT PRIMARY KEY,
    data          TEXT NOT NULL,                 -- JSON com os campos da ficha
    origin        TEXT NOT NULL,                 -- newsletter
    updated_at    TEXT NOT NULL
);

-- Contas/canais oficiais de fornecedores das empresas (window.__CORDEIRO_ACCOUNTS__ da newsletter).
CREATE TABLE IF NOT EXISTS accounts (
    key           TEXT PRIMARY KEY,
    data          TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Até 2 imagens por notícia, salvas em static/imagens/<file>.
CREATE TABLE IF NOT EXISTS news_images (
    news_id       INTEGER NOT NULL REFERENCES news(id),
    position      INTEGER NOT NULL,              -- 1 ou 2
    source_url    TEXT NOT NULL,
    file          TEXT NOT NULL,
    width         INTEGER,
    height        INTEGER,
    sha1          TEXT,
    ahash         TEXT,                          -- hash visual 8x8 (hex), para achar imagens repetidas
    kind          TEXT,                          -- capa (og:image/busca) | corpo (foto do texto)
    created_at    TEXT NOT NULL,
    PRIMARY KEY (news_id, position)
);

-- Hashes visuais de imagens que apareceram em várias notícias (anúncios/imagens-padrão de site).
CREATE TABLE IF NOT EXISTS image_blocklist (
    ahash         TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS errors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER REFERENCES runs(id),
    occurred_at   TEXT NOT NULL,
    engine        TEXT,
    term          TEXT,
    message       TEXT NOT NULL,
    details       TEXT
);
"""

NEWS_FIELDS = (
    "url", "title", "source", "published_at", "summary", "term", "theme", "engine",
    "collected_at", "collected_day", "run_id", "category", "vertical", "ufs",
    "potential", "demand", "prazo", "signal_type", "impacto",
)


def _ts() -> str:
    return config.now().isoformat(timespec="seconds")


@contextmanager
def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(news)")}
        if "manual_class" not in cols:  # migração: 1 = classificação feita pelo analista (newsletter)
            conn.execute("ALTER TABLE news ADD COLUMN manual_class INTEGER DEFAULT 0")
        img_cols = {r["name"] for r in conn.execute("PRAGMA table_info(news_images)")}
        for col in ("ahash", "kind"):
            if col not in img_cols:
                conn.execute(f"ALTER TABLE news_images ADD COLUMN {col} TEXT")


# ---------------------------------------------------------------- execuções
def active_run(max_age_minutes: int = 60):
    """Retorna a execução em andamento (se houver). Execuções travadas há mais tempo são encerradas."""
    limit = (config.now() - timedelta(minutes=max_age_minutes)).isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute(
            "UPDATE runs SET status='falhou', finished_at=?, message='Execução interrompida (sem finalização)' "
            "WHERE status='executando' AND started_at < ?",
            (_ts(), limit),
        )
        return conn.execute("SELECT * FROM runs WHERE status='executando' ORDER BY id DESC LIMIT 1").fetchone()


def start_run(trigger: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO runs(trigger, started_at, status) VALUES (?, ?, 'executando')", (trigger, _ts())
        )
        return cur.lastrowid


def finish_run(run_id: int, status: str, message: str = "", **counts) -> None:
    cols = ", ".join(f"{k}=?" for k in counts)
    sql = f"UPDATE runs SET status=?, finished_at=?, message=?{', ' + cols if cols else ''} WHERE id=?"
    with connect() as conn:
        conn.execute(sql, (status, _ts(), message, *counts.values(), run_id))


def log_search(run_id, engine, term, theme, n_results=0, n_new=0, status="ok", error=None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO searches(run_id, engine, term, theme, executed_at, n_results, n_new, status, error) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, engine, term, theme, _ts(), n_results, n_new, status, error),
        )


def log_error(run_id, message, engine=None, term=None, details=None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO errors(run_id, occurred_at, engine, term, message, details) VALUES (?,?,?,?,?,?)",
            (run_id, _ts(), engine, term, message, details),
        )


# ---------------------------------------------------------------- notícias
def insert_news(item: dict) -> bool:
    """Insere a notícia; se a URL já existir, só atualiza contagem/última vez vista. True = nova."""
    values = [item.get(f) for f in NEWS_FIELDS]
    with connect() as conn:
        cur = conn.execute(
            f"INSERT OR IGNORE INTO news({', '.join(NEWS_FIELDS)}, last_seen_at) "
            f"VALUES ({', '.join('?' * len(NEWS_FIELDS))}, ?)",
            (*values, item["collected_at"]),
        )
        if cur.rowcount:
            return True
        conn.execute(
            "UPDATE news SET times_seen = times_seen + 1, last_seen_at = ? WHERE url = ?",
            (item["collected_at"], item["url"]),
        )
        return False


def news_id(url: str) -> int | None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM news WHERE url=?", (url,)).fetchone()
        return row["id"] if row else None


# ---------------------------------------------------------------- uso do Exa
def exa_used(day: str) -> int:
    with connect() as conn:
        row = conn.execute("SELECT used FROM exa_usage WHERE day=?", (day,)).fetchone()
        return row["used"] if row else 0


def reserve_exa_call(day: str, limit: int) -> bool:
    """Reserva atomicamente uma chamada do Exa no dia. False se o limite já foi atingido."""
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO exa_usage(day, used) VALUES (?, 0)", (day,))
        cur = conn.execute("UPDATE exa_usage SET used = used + 1 WHERE day=? AND used < ?", (day, limit))
        return cur.rowcount == 1


# ---------------------------------------------------------------- leitura p/ painel
def read_sql(sql: str, params=()):
    import pandas as pd

    with connect() as conn:
        return pd.read_sql_query(sql, conn, params=params)
