"""Clientes dos mecanismos de busca: Exa API e DuckDuckGo. Ambos restritos ao Brasil, em português.

Cada função devolve uma lista de dicts no formato comum:
    {title, url, source, published_at (ISO local ou None), summary, image (URL ou None)}
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from . import config

EXA_URL = "https://api.exa.ai/search"

KNOWN_SOURCES = {
    "valor.globo.com": "Valor Econômico",
    "infranews.com.br": "InfraNews",
    "nordesteinvesting.com.br": "Nordeste Investing",
    "movimentoeconomico.com.br": "Movimento Econômico",
    "bvmi.com.br": "BVMI",
    "canalenergia.com.br": "CanalEnergia",
    "exame.com": "Exame",
    "diariodonordeste.verdesmares.com.br": "Diário do Nordeste",
    "opovo.com.br": "O Povo",
    "eixos.com.br": "eixos",
    "clickpetroleoegas.com.br": "Click Petróleo e Gás",
    "cnnbrasil.com.br": "CNN Brasil",
    "g1.globo.com": "g1",
    "bloomberglinea.com.br": "Bloomberg Línea",
    "folha.uol.com.br": "Folha de S.Paulo",
    "estadao.com.br": "Estadão",
    "agenciapara.com.br": "Agência Pará",
    "ceara.gov.br": "Governo do Ceará",
}

TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|mc_|amp$|ref$|ref_src$|ncid$|cmpid$)", re.I)


def normalize_url(url: str) -> str:
    """Remove parâmetros de rastreamento, fragmento e barra final para deduplicar pela URL."""
    parts = urlsplit((url or "").strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k)])
    host = parts.netloc.lower()
    path = re.sub(r"/amp/?$", "/", parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", host, path, query, ""))


def source_from_url(url: str) -> str:
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    for domain, name in KNOWN_SOURCES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host


def to_local_iso(value) -> str | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(config.TZ).isoformat(timespec="seconds")
    except (ValueError, OSError):
        return None


def _clean(text: str, limit: int = 450) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


# ------------------------------------------------------------------- Exa
class ExaError(RuntimeError):
    pass


def search_exa(query: str, api_key: str, cfg: dict) -> list[dict]:
    exa_cfg = cfg["exa"]
    start = datetime.now(timezone.utc) - timedelta(days=int(exa_cfg.get("dias_retroativos", 7)))
    payload = {
        "query": query,
        "type": "auto",
        "category": "news",
        "numResults": int(exa_cfg.get("resultados_por_busca", 10)),
        "userLocation": "BR",  # localização do usuário: Brasil
        "startPublishedDate": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "contents": {"text": {"maxCharacters": 1200}},
    }
    resp = requests.post(
        EXA_URL,
        json=payload,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        timeout=60,
    )
    if resp.status_code >= 400:
        raise ExaError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    results = []
    for r in resp.json().get("results", []):
        url = r.get("url")
        if not url:
            continue
        results.append({
            "title": _clean(r.get("title") or "", 300) or url,
            "url": url,
            "source": source_from_url(url),
            "published_at": to_local_iso(r.get("publishedDate")),
            "summary": _clean(" ".join(r.get("highlights") or []) or r.get("summary") or r.get("text") or ""),
            "image": r.get("image"),
        })
    return results


# ------------------------------------------------------------ Firecrawl
FIRECRAWL_URL = "https://api.firecrawl.dev/v2/search"
TBS_BY_PERIOD = {"d": "qdr:d", "w": "qdr:w", "m": "qdr:m"}
_REL_DATE = re.compile(r"(\d+)\s*(minute|min|hour|hora|day|dia|week|semana|month|m[eê]s)", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTHS.update({"fev": 2, "abr": 4, "mai": 5, "ago": 8, "set": 9, "out": 10, "dez": 12})


def parse_news_date(value) -> str | None:
    """Datas do Firecrawl/Google Notícias: "2 days ago", "há 3 horas", "Oct 12, 2026" ou ISO."""
    if not value:
        return None
    text = str(value).strip()
    iso = to_local_iso(text)
    if iso:
        return iso
    now = datetime.now(timezone.utc)
    if m := _REL_DATE.search(text):
        n, unit = int(m.group(1)), m.group(2).lower()
        delta = {"min": timedelta(minutes=n), "hou": timedelta(hours=n), "hor": timedelta(hours=n),
                 "day": timedelta(days=n), "dia": timedelta(days=n), "wee": timedelta(weeks=n),
                 "sem": timedelta(weeks=n)}.get(unit[:3], timedelta(days=30 * n))
        return (now - delta).astimezone(config.TZ).isoformat(timespec="seconds")
    if re.search(r"yesterday|ontem", text, re.I):
        return (now - timedelta(days=1)).astimezone(config.TZ).isoformat(timespec="seconds")
    if m := re.search(r"([A-Za-zçÇ]{3})[a-zç]*\.?\s+(\d{1,2}),?\s+(\d{4})|(\d{1,2})\s+(?:de\s+)?([A-Za-zçÇ]{3})[a-zç]*\.?\s+(?:de\s+)?(\d{4})", text):
        mon, day, year = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(5), m.group(4), m.group(6))
        if (month := _MONTHS.get(mon.lower())):
            try:
                return datetime(int(year), month, int(day), 12, tzinfo=config.TZ).isoformat(timespec="seconds")
            except ValueError:
                return None
    return None


def search_firecrawl(query: str, api_key: str, cfg: dict) -> tuple[list[dict], int]:
    """Busca de notícias no Firecrawl restrita ao Brasil. Retorna (resultados, créditos usados)."""
    fc = cfg["firecrawl"]
    payload = {
        "query": query,
        "limit": int(fc.get("resultados_por_busca", 10)),
        "sources": ["news"],
        "country": "BR",
        "location": "Brazil",
        "tbs": TBS_BY_PERIOD.get(fc.get("periodo", "w"), "qdr:w"),
        "timeout": 60000,
    }
    resp = requests.post(FIRECRAWL_URL, json=payload, timeout=90,
                         headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    if resp.status_code >= 400:
        raise RuntimeError(f"Firecrawl HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("success", True):
        raise RuntimeError(f"Firecrawl: {data.get('error') or data.get('warning') or 'falha na busca'}")
    results = []
    for r in (data.get("data") or {}).get("news") or []:
        url = r.get("url")
        if not url:
            continue
        results.append({
            "title": _clean(r.get("title") or "", 300) or url,
            "url": url,
            "source": source_from_url(url),
            "published_at": parse_news_date(r.get("date")),
            "summary": _clean(re.sub(r"\*\*", "", r.get("snippet") or r.get("description") or "")),
            "image": r.get("imageUrl"),
        })
    return results, int(data.get("creditsUsed") or 0)


# ------------------------------------------------------------ RSS (fontes diretas)
def search_rss(url: str, cfg: dict, name: str | None = None) -> list[dict]:
    """Notícias de um feed RSS/Atom (ex.: https://brasilmineral.com.br/feed/), dos últimos N dias.
    Sem custo de API: lê o feed publicado pelo próprio site."""
    from email.utils import parsedate_to_datetime
    from html import unescape
    from xml.etree import ElementTree as ET

    from .images import HEADERS

    days = int(cfg.get("rss", {}).get("dias_retroativos", 14))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    resp = requests.get(url, headers=HEADERS, timeout=40)
    if resp.status_code >= 400:
        raise RuntimeError(f"RSS HTTP {resp.status_code}: {url}")
    root = ET.fromstring(resp.content)
    atom = "{http://www.w3.org/2005/Atom}"
    channel = root.findtext("./channel/title") or root.findtext(f"{atom}title") or name
    items = root.findall("./channel/item") or root.findall(f"{atom}entry")
    results = []
    for it in items:
        link = it.findtext("link") or ""
        if not link:
            el = it.find(f"{atom}link")
            link = el.get("href", "") if el is not None else ""
        title = it.findtext("title") or it.findtext(f"{atom}title") or ""
        if not link or not title:
            continue
        raw_date = it.findtext("pubDate") or it.findtext(f"{atom}updated") or it.findtext(f"{atom}published")
        try:
            dt = parsedate_to_datetime(raw_date) if raw_date and "," in raw_date else datetime.fromisoformat(
                str(raw_date).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            dt = None
        if dt and dt < since:
            continue
        desc = it.findtext("description") or it.findtext(f"{atom}summary") or ""
        desc = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(desc))).strip()
        enc = it.find("enclosure")
        image = enc.get("url") if enc is not None and (enc.get("type") or "image").startswith("image") else None
        results.append({
            "title": _clean(unescape(title), 300),
            "url": link.strip(),
            "source": name or channel or source_from_url(link),
            "published_at": dt.astimezone(config.TZ).isoformat(timespec="seconds") if dt else None,
            "summary": _clean(desc),
            "image": image,
        })
    return results


# ------------------------------------------------------------ DuckDuckGo
def _ddgs_class():
    try:
        from ddgs import DDGS  # pacote atual
    except ImportError:  # nome antigo da biblioteca
        from duckduckgo_search import DDGS
    return DDGS


def search_ddg(query: str, cfg: dict, retries: int = 2) -> list[dict]:
    ddg_cfg = cfg["ddg"]
    DDGS = _ddgs_class()
    last_exc = None
    for attempt in range(retries + 1):
        try:
            raw = DDGS().news(
                query,
                region=ddg_cfg.get("regiao", "br-pt"),
                safesearch="off",
                timelimit=ddg_cfg.get("periodo", "w"),
                max_results=int(ddg_cfg.get("resultados_por_busca", 15)),
            ) or []
            break
        except Exception as exc:  # a biblioteca levanta exceções próprias (ex.: RatelimitException)
            last_exc = exc
            if "no results" in str(exc).lower():
                return []
            time.sleep(5 * (attempt + 1))
    else:
        raise last_exc

    results = []
    for r in raw:
        url = r.get("url") or r.get("href")
        if not url:
            continue
        results.append({
            "title": _clean(r.get("title") or "", 300) or url,
            "url": url,
            "source": r.get("source") or source_from_url(url),
            "published_at": to_local_iso(r.get("date")),
            "summary": _clean(r.get("body") or ""),
            "image": r.get("image"),
        })
    return results
