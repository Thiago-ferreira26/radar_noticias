"""Envio de uma notícia/oportunidade (ou de uma obra do Mapa de Obras) como lead para o Bitrix24 (método crm.lead.add).

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

from . import cnpj, config, db
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


def _create_lead(fields: dict, user: dict, record: dict, label: str) -> dict:
    """POST crm.lead.add e registro em crm_leads. record = {news_id, news_url, obra_cod}."""
    url = config.bitrix_webhook_url()
    if not url:
        return {"ok": False, "lead_id": None, "message": "BITRIX_WEBHOOK_URL não configurada (.env ou Secrets)."}
    settings = load_settings()
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
            "INSERT INTO crm_leads(news_id, news_url, obra_cod, lead_id, assigned_id, assigned_name, status, message, "
            "response, sent_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (record.get("news_id"), record.get("news_url"), record.get("obra_cod"), lead_id, int(user["id"]),
             user["nome"], "ok" if ok else "erro", message, raw, config.now().isoformat(timespec="seconds")),
        )
    if not ok:
        db.log_error(None, f"Bitrix: {message}", engine="bitrix", term=label,
                     details=json.dumps({"fields": {k: v for k, v in fields.items() if k != "COMMENTS"}},
                                        ensure_ascii=False) + "\n" + raw)
    return {"ok": ok, "lead_id": lead_id, "message": message}


def send_lead(row: dict, ficha: dict, user: dict, empresa: dict | None = None) -> dict:
    """Cria o lead no Bitrix. Retorna {"ok": bool, "lead_id": int|None, "message": str}.
    empresa: resumo do CNPJ (radar.cnpj.resumo), acrescentado ao corpo do lead."""
    fields = {
        "TITLE": f"[{im_code(row)}] {row.get('title') or 'Oportunidade Radar Cordeiro'}"[:255],
        "COMMENTS": build_body(row, ficha) + (cnpj.bloco_lead(empresa) if empresa else ""),
        "ASSIGNED_BY_ID": int(user["id"]),
        "SOURCE_DESCRIPTION": f"Radar Cordeiro {im_code(row)} — {row.get('url') or ''}"[:255],
    }
    return _create_lead(fields, user, {"news_id": row.get("id"), "news_url": row.get("url")}, row.get("title"))


def build_obra_body(o: dict) -> str:
    """Corpo do lead de uma obra do Mapa de Obras (Obras Online)."""
    def line(label, value):
        return f"<b>{escape(label)}:</b> {escape(str(value))}<br>" if value and value != "-" else ""

    empresas = "".join(f"• {escape(e.get('nome') or '')} — {escape(e.get('papel') or '')}<br>"
                       for e in o.get("empresas") or [])
    return (
        f"<b>Mapa de Obras Cordeiro (Obras Online)</b><br>"
        f"<b>Lead IM:</b> {escape(o['im'])}<br><br>"
        + line("Segmento", o.get("setor"))
        + line("Tipo de obra", o.get("tipo"))
        + line("Nome na fonte", o.get("nome"))
        + line("Local", f"{o.get('cidade')} / {UF_LABEL.get(o.get('uf'), o.get('uf'))}")
        + line("Situação", o.get("status"))
        + line("Fase / etapa atual", o.get("faseCurta") or o.get("fase"))
        + line("Prev. término da fase", o.get("pfase"))
        + line("Prev. entrega da obra", o.get("pent"))
        + line("Subsetor", o.get("subsetor"))
        + line("Especificação", o.get("espec"))
        + line("Investimento", o.get("invest"))
        + line("Valor", o.get("valor"))
        + line("Histórico", o.get("obs"))
        + (f"<br><b>Empresas:</b><br>{empresas}" if empresas else "")
        + "<br>"
        + line("Código Obras Online", o.get("cod"))
        + line("Última atualização na fonte", o.get("atu"))
    )


def send_obra_lead(o: dict, user: dict) -> dict:
    """Cria o lead de uma obra (campos de load_obras: im, faseCurta, empresas…)."""
    title = f"{o.get('tipo') or 'Obra'} — {o.get('cidade')}/{o.get('uf')}"
    fields = {
        "TITLE": f"[{o['im']}] {title}"[:255],
        "COMMENTS": build_obra_body(o),
        "ASSIGNED_BY_ID": int(user["id"]),
        "SOURCE_DESCRIPTION": f"Mapa de Obras Cordeiro {o['im']} — Obras Online"[:255],
    }
    return _create_lead(fields, user, {"obra_cod": o.get("cod")}, title)


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
            "SELECT news_id, lead_id, assigned_name, sent_at FROM crm_leads "
            "WHERE status='ok' AND news_id IS NOT NULL ORDER BY sent_at"
        ).fetchall()
    return {r["news_id"]: dict(r) for r in rows}


def sent_by_obra() -> dict[str, dict]:
    """Último envio com sucesso de cada obra: {cod: {lead_id, assigned_name, sent_at}}"""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT obra_cod, lead_id, assigned_name, sent_at FROM crm_leads "
            "WHERE status='ok' AND obra_cod IS NOT NULL ORDER BY sent_at"
        ).fetchall()
    return {r["obra_cod"]: dict(r) for r in rows}
