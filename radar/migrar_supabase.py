"""Migra o banco local (data/radar.db) e as imagens para o Supabase.

Pré-requisitos no .env: SUPABASE_DB_URL (Postgres) e, para as imagens, SUPABASE_URL e
SUPABASE_SERVICE_KEY. Pode ser rodado mais de uma vez: linhas já existentes são mantidas.

    python -m radar.migrar_supabase
"""
from __future__ import annotations

import sqlite3
import sys

from . import config, db, images


def main() -> int:
    if db.backend() != "postgres":
        print("SUPABASE_DB_URL não configurada no .env — nada a migrar.")
        return 1
    src_path = config.DB_PATH
    if not src_path.exists():
        print(f"Banco local não encontrado: {src_path}")
        return 1

    print("1/4 Criando tabelas no Supabase…")
    db.init_db()

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    counts = {}
    print("2/4 Copiando dados…")
    with db._pg_pool().connection() as pg, pg.transaction():
        for table in db.TABLES:
            exists = src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                continue
            cols = [r["name"] for r in src.execute(f"PRAGMA table_info({table})")]
            rows = [tuple(r[c] for c in cols) for r in src.execute(f"SELECT * FROM {table}")]
            if rows:
                sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                       "ON CONFLICT DO NOTHING")
                with pg.cursor() as cur:
                    cur.executemany(sql, rows)
            counts[table] = len(rows)
            print(f"   {table:16} {len(rows):5} linhas")
        # As colunas de identidade continuam a numeração a partir do maior ID copiado.
        for table in db.IDENTITY_TABLES:
            pg.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                       f"COALESCE((SELECT MAX(id) FROM {table}), 1), (SELECT MAX(id) FROM {table}) IS NOT NULL)")
    src.close()

    print("3/4 Imagens…")
    if images.storage():
        images.ensure_bucket()
        with db.connect() as conn:
            files = [r["file"] for r in conn.execute("SELECT file FROM news_images")]
        sent = missing = 0
        for name in files:
            if (images.IMG_DIR / name).exists():
                images.upload(name)
                sent += 1
            else:
                missing += 1
        print(f"   {sent} imagens enviadas ao bucket '{images.BUCKET}'" + (f" ({missing} sem arquivo local)" if missing else ""))
    else:
        print("   SUPABASE_URL / SUPABASE_SERVICE_KEY não configuradas — imagens não migradas.")

    print("4/4 Conferindo…")
    ok = True
    with db.connect() as conn:
        for table, n in counts.items():
            got = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            flag = "ok" if got >= n else "FALTANDO"
            ok &= got >= n
            print(f"   {table:16} local {n:5} | Supabase {got:5}  {flag}")
    print("Migração concluída." if ok else "Migração com diferenças — veja acima.")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
