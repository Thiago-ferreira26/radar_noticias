"""Envio de uma notícia/oportunidade como lead para o Bitrix24 (método crm.lead.add).

POST {BITRIX_WEBHOOK_URL}crm.lead.add.json
     {"fields": {"TITLE": "[IM-AAAA-NNNN] ...", "COMMENTS": ..., "ASSIGNED_BY_ID": ..., "SOURCE_ID": ...}}
Cada envio (com sucesso ou erro) fica registrado na tabela crm_leads.
"""
from __future__ import annotations

import json
from html import escape
from urllib.parse import urlsplit

import requests
import yaml

from . import config, db
from .ui import UF_LABEL, fmt_date, im_code

BITRIX_CFG = config.BASE_DIR / "config" / "bitrix.yaml"
TIMEOUT = 20


def load_settings() -> dict:
    if not BITRIX_CFG.exists():
        return {"source_id": None, "usuarios": []}
    with open(BITRIX_CFG, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data["usuarios"] = [{"id": int(u["id"]), "nome": str(u["nome"]).strip()} for u in data.get("usuarios") or []]
    return data


def users() -> list[dict]:
    return load_settings()["usuarios"]


def is_configured() -> bool:
    return bool(config.bitrix_webhook_url())


def build_body(row: dict, ficha: dict) -> str:
    """Corpo do lead (campo COMMENTS, aceita HTML simples) com o essencial da oportunidade."""
    def line(label, value):
        return f"<b>{escape(label)}:</b> {escape(str(value))}<br>" if value else ""

    ufs = ", ".join(UF_LABEL.get(u, u) for u in str(row.get("ufs") or "").split(",") if u)
    return (
        f"<b>Radar Cordeiro — Inteligência de Mercado</b><br>"
        f"<b>Lead IM:</b> {im_code(row)}<br><br>"
        f"{escape(row.get('summary') or '')}<br><br>"
        + line("Potencial", row.get("potential"))
        + line("Vertical / categoria", " / ".join(filter(None, [row.get("vertical"), row.get("category")])))
        + line("UF", ufs)
        + line("Prazo da demanda", row.get("prazo"))
        + line("Demanda de guindaste/área", row.get("demand"))
        + line("Impacto para a Cordeiro", row.get("impacto"))
        + "<br>"
        + line("Entrada da Cordeiro", ficha.get("priority"))
        + line("Fase do projeto", ficha.get("phase"))
        + line("Empresa executora", ficha.get("executor"))
        + line("Serviço potencial", ficha.get("need"))
        + line("Próximo passo", (ficha.get("steps") or [None])[0])
        + "<br>"
        + line("Fonte", f"{row.get('source') or ''} — {fmt_date(row.get('published_at'))}")
        + f'<b>Notícia:</b> <a href="{escape(row.get("url") or "")}">{escape(row.get("url") or "")}</a>'
    )


def send_lead(row: dict, ficha: dict, user: dict) -> dict:
    """Cria o lead no Bitrix. Retorna {"ok": bool, "lead_id": int|None, "message": str}."""
    url = config.bitrix_webhook_url()
    if not url:
        return {"ok": False, "lead_id": None, "message": "BITRIX_WEBHOOK_URL não configurada (.env ou Secrets)."}
    settings = load_settings()
    fields = {
        "TITLE": f"[{im_code(row)}] {row.get('title') or 'Oportunidade Radar Cordeiro'}"[:255],
        "COMMENTS": build_body(row, ficha),
        "ASSIGNED_BY_ID": int(user["id"]),
        "SOURCE_DESCRIPTION": f"Radar Cordeiro {im_code(row)} — {row.get('url') or ''}"[:255],
    }
    if settings.get("source_id"):
        fields["SOURCE_ID"] = settings["source_id"]

    ok, lead_id, message, raw = False, None, "", ""
    try:
        resp = requests.post(f"{url}crm.lead.add.json", json={"fields": fields}, timeout=TIMEOUT)
        raw = resp.text[:2000]
        data = resp.json() if resp.content else {}
        if resp.ok and data.get("result"):
            ok, lead_id = True, int(data["result"])
            message = f"Lead #{lead_id} criado para {user['nome']}."
        else:
            message = data.get("error_description") or data.get("error") or f"HTTP {resp.status_code}"
    except (requests.RequestException, ValueError) as exc:
        message = f"Falha ao contatar o Bitrix: {type(exc).__name__}: {exc}"

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO crm_leads(news_id, news_url, lead_id, assigned_id, assigned_name, status, message, "
            "response, sent_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (row.get("id"), row.get("url"), lead_id, int(user["id"]), user["nome"], "ok" if ok else "erro",
             message, raw, config.now().isoformat(timespec="seconds")),
        )
    if not ok:
        db.log_error(None, f"Bitrix: {message}", engine="bitrix", term=row.get("title"),
                     details=json.dumps({"fields": {k: v for k, v in fields.items() if k != "COMMENTS"}},
                                        ensure_ascii=False) + "\n" + raw)
    return {"ok": ok, "lead_id": lead_id, "message": message}


def lead_url(lead_id) -> str | None:
    """Link do lead na interface do Bitrix (mesmo domínio do webhook, sem o token)."""
    url = config.bitrix_webhook_url()
    if not url or not lead_id:
        return None
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/crm/lead/details/{int(lead_id)}/"


def sent_by_news() -> dict[int, dict]:
    """Último envio com sucesso de cada notícia: {news_id: {lead_id, assigned_name, sent_at}}"""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT news_id, lead_id, assigned_name, sent_at FROM crm_leads WHERE status='ok' ORDER BY sent_at"
        ).fetchall()
    return {r["news_id"]: dict(r) for r in rows}
