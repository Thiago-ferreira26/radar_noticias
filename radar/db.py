"""Acesso ao banco (SQLite local ou Postgres do Supabase): execuções, buscas, notícias, fichas, imagens, obras,
leads e erros."""
from __future__ import annotations

import atexit
import sqlite3
import threading
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

-- Uso diário de APIs pagas além do Exa (ex.: firecrawl): buscas e créditos.
CREATE TABLE IF NOT EXISTS api_usage (
    engine        TEXT NOT NULL,
    day           TEXT NOT NULL,                 -- YYYY-MM-DD (fuso local)
    used          INTEGER NOT NULL DEFAULT 0,    -- buscas feitas
    credits       INTEGER NOT NULL DEFAULT 0,    -- créditos informados pela API
    PRIMARY KEY (engine, day)
);

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

-- Leads enviados ao Bitrix24 a partir dos cards (sucesso e erro).
CREATE TABLE IF NOT EXISTS crm_leads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id       INTEGER REFERENCES news(id),
    news_url      TEXT,
    lead_id       INTEGER,                       -- ID do lead criado no Bitrix (se ok)
    assigned_id   INTEGER NOT NULL,              -- ASSIGNED_BY_ID
    assigned_name TEXT,
    status        TEXT NOT NULL,                 -- ok | erro
    message       TEXT,
    response      TEXT,
    sent_at       TEXT NOT NULL
);

-- Mapa de Obras (Obras Online): uma linha por obra, com o JSON da ficha. ativa = 0: saiu do último arquivo.
CREATE TABLE IF NOT EXISTS obras (
    cod           TEXT PRIMARY KEY,              -- código da obra no Obras Online
    setor         TEXT,                          -- Eólico | Mineração | Data Center | Infraestrutura
    uf            TEXT,
    status        TEXT,
    data          TEXT NOT NULL,                 -- JSON da obra (formato do mapa_obras_cordeiro-PAINEL.html)
    ativa         INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Cada importação do Mapa de Obras (manual, agendada ou pela linha de comando).
CREATE TABLE IF NOT EXISTS obras_imports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    imported_at   TEXT NOT NULL,
    origem        TEXT NOT NULL,
    file_name     TEXT,
    sha1          TEXT,
    n_total       INTEGER DEFAULT 0,
    n_new         INTEGER DEFAULT 0,
    n_updated     INTEGER DEFAULT 0,
    n_removed     INTEGER DEFAULT 0
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


# Colunas acrescentadas depois da primeira versão do esquema (migração automática).
EXTRA_COLUMNS = [("news", "manual_class", "INTEGER DEFAULT 0"),  # 1 = classificação do analista (newsletter)
                 ("news_images", "ahash", "TEXT"), ("news_images", "kind", "TEXT"),
                 ("runs", "firecrawl_used", "INTEGER DEFAULT 0"),
                 ("crm_leads", "obra_cod", "TEXT")]  # lead criado a partir de uma obra do Mapa de Obras
# Ordem de cópia/criação respeitando as chaves estrangeiras.
TABLES = ["runs", "searches", "news", "dossiers", "accounts", "exa_usage", "api_usage", "news_images",
          "image_blocklist", "crm_leads", "obras", "obras_imports", "errors"]
IDENTITY_TABLES = ["runs", "searches", "news", "crm_leads", "obras_imports", "errors"]


def _encode_password(url: str) -> str:
    """Codifica caracteres especiais da senha (ex.: '@' → '%40') quando a URL foi colada com a senha crua.
    Usa o ÚLTIMO '@' da parte de autenticação como separador do host."""
    from urllib.parse import quote, unquote

    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    netloc, slash, tail = rest.partition("/")
    if netloc.count("@") <= 1:
        return url
    userinfo, host = netloc.rsplit("@", 1)
    user, _, password = userinfo.partition(":")
    return f"{scheme}://{user}:{quote(unquote(password), safe='')}@{host}{slash}{tail}"


def database_url() -> str | None:
    """Postgres do Supabase (SUPABASE_DB_URL). Sem ela, o painel usa o SQLite local em data/radar.db."""
    url = config.secret("SUPABASE_DB_URL")
    return _encode_password(url) if url else None


def backend() -> str:
    return "postgres" if database_url() else "sqlite"


def pg_schema() -> list[str]:
    """Mesmo esquema do SQLite, traduzido para Postgres, um comando por item."""
    ddl = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
    ddl = "\n".join(line.split("--")[0].rstrip() for line in ddl.splitlines())
    stmts = [s.strip() for s in ddl.split(";") if s.strip()]
    stmts += [f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {c} {d}" for t, c, d in EXTRA_COLUMNS]
    # Supabase expõe o esquema public pela API REST (chaves anon/publishable). RLS ligado e sem políticas
    # bloqueia esse acesso; o painel conecta como dono das tabelas (postgres) e não é afetado.
    stmts += [f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY" for t in TABLES]
    return stmts


class _PgConn:
    """Adapta a conexão psycopg à interface usada no projeto (sqlite3): execute(sql com '?', params)
    e linhas acessadas por nome (r["coluna"])."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=()):
        from psycopg.rows import dict_row

        cur = self._conn.cursor(row_factory=dict_row)
        cur.execute(sql.replace("%", "%%").replace("?", "%s") if params else sql, tuple(params) or None)
        return cur


_pool = None


class DatabaseConnectionError(RuntimeError):
    """Falha ao conectar no Supabase, com o motivo real e a dica de correção (sem expor a senha)."""


def describe_url(url: str | None = None) -> dict:
    """Partes da SUPABASE_DB_URL para diagnóstico, com a senha mascarada."""
    from psycopg.conninfo import conninfo_to_dict

    try:
        info = conninfo_to_dict(url or database_url() or "")
    except Exception as exc:  # URL malformada
        return {"erro": f"URL inválida: {type(exc).__name__}"}
    return {k: ("***" if k == "password" else v) for k, v in info.items()}


def _hints(info: dict) -> list[str]:
    host, user, port = str(info.get("host", "")), str(info.get("user", "")), str(info.get("port", "5432"))
    tips = []
    if "@" in host or "@" in user or not host:
        tips.append("A senha parece ter '@' sem codificar: na URL, troque cada '@' da senha por '%40' "
                    "(ex.: minha@senha → minha%40senha).")
    if host.startswith("db.") and host.endswith(".supabase.co"):
        tips.append("O host direto db.<projeto>.supabase.co só tem IPv6 e não funciona no Streamlit Cloud. "
                    "Use a URL do 'Session pooler': aws-1-us-west-2.pooler.supabase.com, porta 5432, "
                    "usuário postgres.<projeto>.")
    if host.endswith("pooler.supabase.com") and not user.startswith("postgres."):
        tips.append("No pooler o usuário é 'postgres.<id-do-projeto>' (ex.: postgres.cbqflpapzmywfxcebjpa).")
    if "[YOUR-PASSWORD]" in (database_url() or ""):
        tips.append("Substitua [YOUR-PASSWORD] pela senha do banco.")
    if port not in ("5432", "6543"):
        tips.append(f"Porta {port} incomum: o Session pooler usa 5432.")
    return tips


def check_connection(timeout: int = 15) -> None:
    """Abre uma conexão de teste e, se falhar, levanta DatabaseConnectionError com o motivo e as dicas."""
    import psycopg

    try:
        psycopg.connect(database_url(), connect_timeout=timeout, prepare_threshold=None).close()
    except Exception as exc:
        from psycopg.conninfo import conninfo_to_dict

        info = describe_url()
        reason = " ".join(str(exc).split())
        try:
            password = conninfo_to_dict(database_url()).get("password") or ""
        except Exception:
            password = ""
        if password:  # nunca mostrar a senha
            reason = reason.replace(password, "***")
        host = str(info.get("host", ""))
        if "@" in host:  # '@' da senha sem codificar: o trecho antes do '@' é parte da senha
            leaked, real_host = host.rsplit("@", 1)
            reason = reason.replace(leaked + "@", "***@")
            info["host"] = "***@" + real_host
        shown = ", ".join(f"{k}={v}" for k, v in info.items() if k in ("host", "port", "user", "dbname", "erro"))
        tips = _hints(info)
        raise DatabaseConnectionError(
            f"Não foi possível conectar ao Supabase ({shown}). Motivo: {reason[-400:]}"
            + ("\n\nComo corrigir:\n- " + "\n- ".join(tips) if tips else "")
        ) from None


def _pg_pool():
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool

        check_connection()  # mostra o erro real em vez de um "PoolTimeout" genérico

        # autocommit: cada comando é uma única ida e volta ao servidor (o Supabase pode estar longe, ~200 ms);
        # as operações do painel são de um comando só, e a migração usa transação explícita.
        # prepare_threshold=None: compatível com o pooler do Supabase (Supavisor).
        # check: testa a conexão antes de entregá-la. O Supabase fecha conexões paradas, e a TV ligada o dia
        # todo dava "server closed the connection unexpectedly" na recarga seguinte.
        _pool = ConnectionPool(database_url(), min_size=1, max_size=6, open=True, timeout=30,
                               check=ConnectionPool.check_connection, max_idle=300,
                               kwargs={"autocommit": True, "prepare_threshold": None})
        atexit.register(_pool.close)  # fecha antes do encerramento do Python (evita aviso no fim de scripts)
    return _pool


@contextmanager
def connect():
    if backend() == "postgres":
        with _pg_pool().connection() as conn:  # commit ao sair sem erro; rollback se houver exceção
            yield _PgConn(conn)
        return
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


_initialized = False
_init_lock = threading.Lock()  # sessões do Streamlit (threads) abrindo juntas davam DeadlockDetected no DDL


def init_db() -> None:
    global _initialized
    if _initialized and backend() == "postgres":  # no Postgres o esquema é conferido uma vez por processo
        return
    with _init_lock:
        if _initialized and backend() == "postgres":
            return
        _create_schema()
        _initialized = True


def _create_schema() -> None:
    with connect() as conn:
        if backend() == "postgres":
            conn.execute("; ".join(pg_schema()))  # um envio só (sem parâmetros, vários comandos)
        else:
            conn.executescript(SCHEMA)
            for table, col, decl in EXTRA_COLUMNS:
                cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                if col not in cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


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
            "INSERT INTO runs(trigger, started_at, status) VALUES (?, ?, 'executando') RETURNING id",
            (trigger, _ts()),
        )
        return cur.fetchone()["id"]


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
            f"INSERT INTO news({', '.join(NEWS_FIELDS)}, last_seen_at) "
            f"VALUES ({', '.join('?' * len(NEWS_FIELDS))}, ?) ON CONFLICT DO NOTHING",
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
        conn.execute("INSERT INTO exa_usage(day, used) VALUES (?, 0) ON CONFLICT DO NOTHING", (day,))
        cur = conn.execute("UPDATE exa_usage SET used = used + 1 WHERE day=? AND used < ?", (day, limit))
        return cur.rowcount == 1


def api_used(engine: str, day: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT used, credits FROM api_usage WHERE engine=? AND day=?", (engine, day)).fetchone()
        return {"used": row["used"], "credits": row["credits"]} if row else {"used": 0, "credits": 0}


def reserve_api_call(engine: str, day: str, limit: int) -> bool:
    """Reserva atomicamente uma busca do mecanismo no dia. False se o limite já foi atingido."""
    with connect() as conn:
        conn.execute("INSERT INTO api_usage(engine, day, used, credits) VALUES (?, ?, 0, 0) ON CONFLICT DO NOTHING",
                     (engine, day))
        cur = conn.execute("UPDATE api_usage SET used = used + 1 WHERE engine=? AND day=? AND used < ?",
                           (engine, day, limit))
        return cur.rowcount == 1


def add_api_credits(engine: str, day: str, credits: int) -> None:
    if credits:
        with connect() as conn:
            conn.execute("UPDATE api_usage SET credits = credits + ? WHERE engine=? AND day=?", (credits, engine, day))


# ---------------------------------------------------------------- leitura p/ painel
def read_sql(sql: str, params=()):
    import pandas as pd

    with connect() as conn:
        if backend() == "sqlite":
            return pd.read_sql_query(sql, conn, params=params)
        cur = conn.execute(sql, params)
        cols = [c.name for c in cur.description]
        return pd.DataFrame([[r[c] for c in cols] for r in cur.fetchall()], columns=cols)
