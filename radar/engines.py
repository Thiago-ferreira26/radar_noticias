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
