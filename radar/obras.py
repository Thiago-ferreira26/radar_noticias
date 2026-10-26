"""Mapa de Obras: obras do Obras Online (eólico, mineração, data center e infraestrutura).

As obras vêm do painel "mapa_obras_cordeiro-PAINEL.html" (bloco `const DB = {...}`) ou de um JSON com a
lista `obras`. Cada importação é um retrato completo: obras que não estão no arquivo saem do painel e da
TV (ativa = 0), mas continuam no banco.

    python -m radar.obras caminho/mapa_obras_cordeiro-PAINEL.html   # importa um arquivo
    python -m radar.obras --pasta                                   # importa o mais recente de OBRAS_PASTA
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

from . import config, db

MAP_PATH = Path(__file__).resolve().parent / "brasil_mapa.json"
PANEL_TEMPLATE = Path(__file__).resolve().parent / "obras.html"
NEW_DAYS = 7
SETORES = {"Eólico": "#00897E", "Mineração": "#B24B2E", "Data Center": "#3F64B0", "Infraestrutura": "#C97418",
           "Top 30": "#7B4FA6"}
UF_ND = "UF não definida"  # obras sem local definido na fonte (uf "ND", fora do mapa)
EM_CONSTRUCAO = "Obra em Construção"
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
DB_RE = re.compile(r"const\s+DB\s*=\s*(\{.*?\});?\s*$", re.M)


def ob_code(o: dict) -> str:
    """Código de rastreio da obra no padrão da Inteligência de Mercado (busca "IM-" no Bitrix acha tudo)."""
    return f"IM-OBR-{o.get('cod')}"


def parse_dmy(value) -> date | None:
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", str(value or "").strip())
    return date(int(m[3]), int(m[2]), int(m[1])) if m else None


def entrega_key(value) -> tuple[int, int] | None:
    """'dez/2029' → (2029, 12)."""
    m = re.match(r"^([a-z]{3})/(\d{4})$", str(value or "").strip())
    return (int(m[2]), MESES.index(m[1]) + 1) if m and m[1] in MESES else None


def fase_curta(fase: str) -> str:
    return (re.sub(r"\s*\(Execução\)", "", fase or "")
            .replace("Estudo Viab. Econ / Téc / Amb", "Estudo de viabilidade (econ./téc./amb.)"))


def parse_file(text: str) -> list[dict]:
    """Lista de obras do HTML do painel (const DB = {...}) ou de um JSON ({"obras": [...]} ou [...])."""
    text = text.lstrip("﻿")
    if text.lstrip().startswith(("{", "[")):
        data = json.loads(text)
    else:
        m = DB_RE.search(text)
        if not m:
            raise ValueError("Arquivo sem o bloco 'const DB = {...}' do Mapa de Obras.")
        data = json.loads(m.group(1))
    obras = data["obras"] if isinstance(data, dict) else data
    obras = [o for o in obras if isinstance(o, dict) and o.get("cod")]
    if not obras:
        raise ValueError("Nenhuma obra encontrada no arquivo.")
    return obras


def import_obras(text: str, origem: str = "manual", file_name: str = "") -> dict:
    """Grava as obras (insere novas, atualiza as existentes e desativa as que saíram do arquivo)."""
    db.init_db()
    obras = parse_file(text)
    sha1 = hashlib.sha1(text.encode("utf-8")).hexdigest()
    now = config.now().isoformat(timespec="seconds")
    cods = {str(o["cod"]) for o in obras}
    with db.connect() as conn:
        old = {r["cod"]: r["data"] for r in conn.execute("SELECT cod, data FROM obras")}
        active_before = {r["cod"] for r in conn.execute("SELECT cod FROM obras WHERE ativa=1")}
        n_new = n_upd = 0
        for o in obras:
            cod, data = str(o["cod"]), json.dumps(o, ensure_ascii=False, sort_keys=True)
            if cod not in old:
                n_new += 1
            elif old[cod] != data:
                n_upd += 1
            conn.execute(
                "INSERT INTO obras(cod, setor, uf, status, data, ativa, first_seen_at, updated_at) "
                "VALUES (?,?,?,?,?,1,?,?) ON CONFLICT(cod) DO UPDATE SET setor=excluded.setor, uf=excluded.uf, "
                "status=excluded.status, data=excluded.data, ativa=1, updated_at=excluded.updated_at",
                (cod, o.get("setor"), o.get("uf"), o.get("status"), data, now, now),
            )
        removed = active_before - cods
        for cod in removed:
            conn.execute("UPDATE obras SET ativa=0, updated_at=? WHERE cod=?", (now, cod))
        conn.execute(
            "INSERT INTO obras_imports(imported_at, origem, file_name, sha1, n_total, n_new, n_updated, n_removed) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (now, origem, file_name, sha1, len(obras), n_new, n_upd, len(removed)),
        )
    return {"total": len(obras), "novas": n_new, "atualizadas": n_upd, "removidas": len(removed)}


def last_import() -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM obras_imports ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def auto_import(origem: str = "agendado") -> dict | None:
    """Importa o HTML mais recente da pasta OBRAS_PASTA (.env/Secrets), se ele mudou desde a última importação.
    Basta salvar a versão nova do mapa_obras_cordeiro-PAINEL.html na pasta para o painel e a TV atualizarem."""
    folder = config.secret("OBRAS_PASTA")
    if not folder or not Path(folder).is_dir():
        return None
    files = sorted((p for p in Path(folder).glob("*.htm*") if "obra" in p.name.lower()),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    # A pasta pode ter outros painéis com "obras" no nome: vale o mais recente que tenha o bloco const DB.
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if DB_RE.search(text):
            break
    else:
        return None
    last = last_import()
    if last and last["sha1"] == hashlib.sha1(text.encode("utf-8")).hexdigest():
        return {"total": last["n_total"], "novas": 0, "atualizadas": 0, "removidas": 0, "sem_mudanca": True}
    try:
        return import_obras(text, origem, path.name)
    except ValueError as exc:
        db.log_error(None, f"Obras: {exc}", engine="obras", term=path.name)
        return None


def load_obras(only_active: bool = True) -> list[dict]:
    """Obras do banco com os campos derivados usados no painel, na TV, no Excel e no Bitrix."""
    db.init_db()
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM obras" + (" WHERE ativa=1" if only_active else "")).fetchall()
        first = conn.execute("SELECT MIN(imported_at) AS t FROM obras_imports").fetchone()
    first_import = (first["t"] if first else None) or ""
    new_since = (config.today() - timedelta(days=NEW_DAYS)).isoformat()
    today = config.today()
    out = []
    for r in rows:
        o = json.loads(r["data"])
        o["cod"] = str(o["cod"])
        o["im"] = ob_code(o)
        # "Nova" = entrou depois da primeira importação, nos últimos 7 dias (na carga inicial nenhuma é nova).
        o["isNew"] = r["first_seen_at"] > first_import and r["first_seen_at"][:10] >= new_since
        o["faseCurta"] = fase_curta(o.get("fase"))
        d = parse_dmy(o.get("pfase"))
        o["daysTerm"] = (d - today).days if d else None
        o["empresas"] = o.get("empresas") or []
        out.append(o)
    return out


def sort_for_tv(obras: list[dict]) -> list[dict]:
    """Ordem do Modo TV: novas primeiro, depois a fase que termina antes (vencidas e sem data no fim)."""
    def key(o):
        d = o["daysTerm"]
        return (not o["isNew"], 0 if d is not None and d >= 0 else 1 if d is not None else 2,
                abs(d) if d is not None else 0, o["cod"])
    return sorted(obras, key=key)


def panel_data(obras: list[dict]) -> dict:
    """Dados no formato do painel original (mapa + obras)."""
    base = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    base["obras"] = obras
    return base


def panel_html(obras: list[dict], no_translate_js: str = "") -> str:
    t = config.today()
    return (PANEL_TEMPLATE.read_text(encoding="utf-8")
            .replace("__DATA__", json.dumps(panel_data(obras), ensure_ascii=False).replace("</", "<\\/"))
            .replace("__TODAY__", f"{t.year}, {t.month - 1}, {t.day}")
            .replace("__NO_TRANSLATE__", no_translate_js))


def build_tv_deck(max_obras: int | None = None) -> dict:
    """Modo TV das obras: capa (indicadores + mapa) e um slide por obra ativa."""
    from collections import Counter

    from .ui import UF_LABEL

    obras = sort_for_tv(load_obras())
    if max_obras:
        obras = obras[:max_obras]
    last = last_import()
    atus = [d for d in (parse_dmy(o.get("atu")) for o in obras) if d]
    ufs = Counter(o["uf"] for o in obras if o["uf"] != "ND")
    cover = {
        "total": len(obras),
        "build": sum(o.get("status") == EM_CONSTRUCAO for o in obras),
        "soon": sum(o["daysTerm"] is not None and 0 <= o["daysTerm"] <= 60 for o in obras),
        "ufs": len(ufs),
        "updated": max(atus).strftime("%d/%m/%Y") if atus else "—",
        "imported": (last["imported_at"][:10] if last else ""),
        "by_setor": [[k, sum(o.get("setor") == k for o in obras), c] for k, c in SETORES.items()],
        "by_uf": [[UF_LABEL.get(u, u), n, "#3f8f8a"] for u, n in ufs.most_common(4)],
    }
    slides = [{
        "im": o["im"], "cod": o["cod"], "setor": o.get("setor") or "", "setorColor": SETORES.get(o.get("setor"), "#4a6a86"),
        "tipo": o.get("tipo") or "", "nome": o.get("nome") or "", "cidade": o.get("cidade") or "", "uf": o.get("uf") or "",
        "ufNome": UF_ND if o.get("uf") == "ND" else UF_LABEL.get(o.get("uf"), o.get("uf")), "status": o.get("status") or "", "fase": o["faseCurta"],
        "pfase": o.get("pfase") or "—", "pent": o.get("pent") or "—", "atu": o.get("atu") or "—",
        "daysTerm": o["daysTerm"], "subsetor": o.get("subsetor") or "", "espec": o.get("espec") or "",
        "invest": o.get("invest") or "", "valor": o.get("valor") or "-", "obs": o.get("obs") or "",
        "empresas": o["empresas"][:5], "x": o.get("x"), "y": o.get("y"), "geoAprox": bool(o.get("geoAprox")),
        "isNew": o["isNew"],
    } for o in obras]
    return {"map": json.loads(MAP_PATH.read_text(encoding="utf-8")), "cover": cover, "slides": slides,
            "generatedAt": config.now().isoformat(timespec="seconds")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa as obras do Mapa de Obras para o banco")
    parser.add_argument("arquivo", nargs="?", help="HTML do Mapa de Obras ou JSON com as obras")
    parser.add_argument("--pasta", action="store_true", help="importa o arquivo mais recente de OBRAS_PASTA")
    args = parser.parse_args()
    if args.arquivo:
        path = Path(args.arquivo)
        res = import_obras(path.read_text(encoding="utf-8"), "linha de comando", path.name)
    elif args.pasta:
        res = auto_import("linha de comando")
        if res is None:
            raise SystemExit("OBRAS_PASTA não configurada, inexistente ou sem HTML de obras.")
    else:
        parser.error("informe o arquivo ou --pasta")
    print(f"Obras: {res['total']} no arquivo · {res['novas']} novas · {res['atualizadas']} atualizadas · "
          f"{res['removidas']} removidas" + (" (arquivo sem mudança)" if res.get("sem_mudanca") else ""))


if __name__ == "__main__":
    main()
