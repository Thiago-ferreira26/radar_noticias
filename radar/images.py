"""Imagens das notícias: até 2 por notícia, baixadas e redimensionadas em static/imagens/.

Fontes, em ordem: imagem devolvida pelo mecanismo de busca (DuckDuckGo/Exa) e imagens de
capa da própria matéria (og:image / twitter:image). Arquivos ficam em static/ porque o
Streamlit serve essa pasta em /app/static/ (server.enableStaticServing).

Preencher imagens das notícias que ainda não têm (ex.: base antiga ou importada):
    python -m radar.images
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from urllib.parse import urljoin

import requests
from PIL import Image

from . import config, db

log = logging.getLogger("radar")

MAX_IMAGES = 2
IMG_DIR = config.BASE_DIR / "static" / "imagens"
STATIC_URL = "/app/static/imagens/"
MAX_BYTES = 8_000_000
MIN_W, MIN_H = 320, 180          # descarta ícones, logos e pixels de rastreamento
MAX_SIZE = (1600, 1000)          # suficiente para uma TV Full HD
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
META_RE = re.compile(
    r"<meta\b[^>]*?(?:property|name)\s*=\s*[\"'](?:og:image(?::secure_url|:url)?|twitter:image(?::src)?)[\"'][^>]*>",
    re.I,
)
CONTENT_RE = re.compile(r"content\s*=\s*[\"']([^\"']+)[\"']", re.I)


IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
IMG_SRC_RE = re.compile(r"\b(?:data-src|data-lazy-src|src)\s*=\s*[\"']([^\"']+\.(?:jpe?g|png|webp)(?:\?[^\"']*)?)[\"']", re.I)
SKIP_RE = re.compile(r"logo|icon|avatar|sprite|banner|publicidade|(?<![a-z])ads?[/_-]|placeholder|emoji|gravatar|pixel", re.I)


def _ahash(img: Image.Image) -> int:
    """Hash visual 8x8: a mesma foto em tamanhos/compressões diferentes gera hashes quase iguais."""
    small = img.convert("L").resize((8, 8))
    px = list(small.getdata())
    avg = sum(px) / 64
    return sum(1 << i for i, p in enumerate(px) if p > avg)


def _similar(a: int, b: int) -> bool:
    return bin(a ^ b).count("1") <= 6


def page_images(url: str) -> tuple[list[str], list[str]]:
    """(capas, fotos do corpo) da página da notícia.

    Capas: og:image / twitter:image. Corpo: só <img> dentro do primeiro bloco <article>…</article>,
    para não pegar anúncios, menus e fotos de "leia também" que ficam fora do texto da matéria.
    """
    try:
        with requests.get(url, headers=HEADERS, timeout=12, stream=True) as resp:
            if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", "html"):
                return [], []
            raw = b""
            for chunk in resp.iter_content(65536):
                raw += chunk
                if len(raw) > 1_500_000:
                    break
            encoding = resp.encoding or "utf-8"
    except requests.RequestException:
        return [], []
    page = raw.decode(encoding, errors="ignore")

    def clean(src: str) -> str | None:
        src = urljoin(url, unescape(src.strip()))
        return src if src.startswith("http") and not SKIP_RE.search(src) else None

    covers = []
    for tag in META_RE.findall(page):
        m = CONTENT_RE.search(tag)
        if m and (src := clean(m.group(1))) and src not in covers:
            covers.append(src)

    body = []
    low = page.lower()
    start = low.find("<article")
    if start >= 0:
        end = low.find("</article>", start)
        for tag in IMG_TAG_RE.findall(page[start:end if end > 0 else None])[:12]:
            m = IMG_SRC_RE.search(tag)
            if m and (src := clean(m.group(1))) and src not in covers and src not in body:
                body.append(src)
    return covers, body[:4]


def _download(src: str) -> tuple[bytes, Image.Image] | None:
    try:
        with requests.get(src, headers=HEADERS, timeout=15, stream=True) as resp:
            if resp.status_code >= 400 or not resp.headers.get("content-type", "image/").startswith("image/"):
                return None
            data = b""
            for chunk in resp.iter_content(131072):
                data += chunk
                if len(data) > MAX_BYTES:
                    return None
        img = Image.open(io.BytesIO(data))
        img.load()
    except (requests.RequestException, OSError, Image.DecompressionBombError):
        return None
    if img.width < MIN_W or img.height < MIN_H:
        return None
    return data, img


def _save(img: Image.Image, name: str) -> tuple[str, int, int]:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    if img.mode not in ("RGB", "L"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
        img = bg
    img = img.convert("RGB")
    img.thumbnail(MAX_SIZE)
    img.save(IMG_DIR / name, "JPEG", quality=82, optimize=True, progressive=True)
    return name, img.width, img.height


def store_images(news_id: int, page_url: str, hints: list[str] | None = None) -> int:
    """Baixa até MAX_IMAGES imagens para a notícia. Retorna quantas imagens ela tem ao final."""
    with db.connect() as conn:
        have = conn.execute("SELECT position, source_url, sha1, ahash FROM news_images WHERE news_id=?", (news_id,)).fetchall()
        # Hashes das imagens de OUTRAS notícias: imagem repetida entre notícias é anúncio ou imagem-padrão do site.
        others = [int(r["ahash"], 16) for r in conn.execute(
            "SELECT ahash FROM news_images WHERE news_id<>? AND ahash IS NOT NULL "
            "UNION SELECT ahash FROM image_blocklist", (news_id,))]
    if len(have) >= MAX_IMAGES:
        return len(have)
    seen_src = {r["source_url"] for r in have}
    seen_hash = {r["sha1"] for r in have}
    seen_visual = [int(r["ahash"], 16) for r in have if r["ahash"]]
    count = len(have)
    used: set[int] = set()

    covers, body = page_images(page_url)
    candidates = [(s, "capa") for s in dict.fromkeys([h for h in (hints or []) if h] + covers)]
    candidates += [(s, "corpo") for s in body if s not in dict(candidates)]
    for src, kind in candidates:
        if count >= MAX_IMAGES:
            break
        if src in seen_src:
            continue
        got = _download(src)
        if not got:
            continue
        data, img = got
        ratio = img.width / img.height
        if kind == "corpo" and not 0.6 <= ratio <= 2.4:  # banners e tiras de anúncio
            continue
        sha1 = hashlib.sha1(data).hexdigest()
        visual = _ahash(img)
        if sha1 in seen_hash or any(_similar(visual, v) for v in seen_visual + others):
            continue
        position = min(set(range(1, MAX_IMAGES + 1)) - {r["position"] for r in have} - used)
        used.add(position)
        name, w, hgt = _save(img, f"{news_id}_{position}.jpg")
        with db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO news_images(news_id, position, source_url, file, width, height, sha1, ahash, "
                "kind, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (news_id, position, src, name, w, hgt, sha1, f"{visual:016x}", kind,
                 config.now().isoformat(timespec="seconds")),
            )
        seen_src.add(src)
        seen_hash.add(sha1)
        seen_visual.append(visual)
        count += 1
    return count


def store_many(jobs: list[tuple[int, str, list[str]]], workers: int = 6) -> int:
    """Processa vários (news_id, url, dicas) em paralelo. Retorna o total de imagens salvas."""
    def run(job):
        try:
            return store_images(*job)
        except Exception as exc:  # imagem nunca deve derrubar a coleta
            log.warning("Imagens da notícia %s falharam: %s", job[0], exc)
            return 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        total = sum(pool.map(run, jobs))
    return total - purge_repeated()


def purge_repeated() -> int:
    """Remove imagens visualmente iguais em notícias diferentes (anúncio/imagem-padrão) e bloqueia o hash."""
    with db.connect() as conn:
        rows = conn.execute("SELECT news_id, position, file, ahash FROM news_images WHERE ahash IS NOT NULL").fetchall()
        hashes = [(r, int(r["ahash"], 16)) for r in rows]
        bad = set()
        for i, (a, ha) in enumerate(hashes):
            for b, hb in hashes[i + 1:]:
                if a["news_id"] != b["news_id"] and _similar(ha, hb):
                    bad.update({(a["news_id"], a["position"]), (b["news_id"], b["position"])})
        now = config.now().isoformat(timespec="seconds")
        for r, _ in hashes:
            if (r["news_id"], r["position"]) in bad:
                conn.execute("INSERT OR IGNORE INTO image_blocklist(ahash, created_at) VALUES (?,?)", (r["ahash"], now))
                conn.execute("DELETE FROM news_images WHERE news_id=? AND position=?", (r["news_id"], r["position"]))
                (IMG_DIR / r["file"]).unlink(missing_ok=True)
    if bad:
        log.info("%d imagens repetidas entre notícias removidas (anúncios/imagens-padrão).", len(bad))
    return len(bad)


def images_by_news() -> dict[int, list[str]]:
    """{news_id: [url pública da imagem 1, imagem 2]}"""
    with db.connect() as conn:
        rows = conn.execute("SELECT news_id, file FROM news_images ORDER BY news_id, position").fetchall()
    out: dict[int, list[str]] = {}
    for r in rows:
        if (IMG_DIR / r["file"]).exists():
            out.setdefault(r["news_id"], []).append(STATIC_URL + r["file"])
    return out


def backfill(limit: int | None = None) -> int:
    db.init_db()
    sql = ("SELECT n.id, n.url FROM news n WHERE (SELECT COUNT(*) FROM news_images i WHERE i.news_id=n.id) < ? "
           "ORDER BY n.collected_at DESC")
    with db.connect() as conn:
        rows = conn.execute(sql + (f" LIMIT {int(limit)}" if limit else ""), (MAX_IMAGES,)).fetchall()
    return store_many([(r["id"], r["url"], []) for r in rows])


if __name__ == "__main__":
    import sys

    from .collector import setup_logging

    setup_logging()
    total = backfill(int(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(f"{total} imagens no total para as notícias processadas.")
