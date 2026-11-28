"""Web search for Narwhal's lab3 models, through the homelab's own SearXNG
(lab1 CT 116), so nothing leaves the network but the search itself.

The model gets two tools: web_search (titles, links and snippets) and
open_page (the readable text of one result). open_page only fetches public
http(s) addresses: a page the model read can't steer it into the homelab.
"""

import html
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request

from process import config as cfg

TIMEOUT = 10
MAX_RESULTS = 6
PAGE_CHARS = 8000
UA = "Mozilla/5.0 (Narwhal search)"

TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web. Use it when you don't know something, or it may have changed "
                       "since you were trained (versions, news, prices, docs, CVEs).",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What to search for, as you'd type it into a search engine."}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "open_page",
        "description": "Read the text of a web page, such as a search result, when its snippet isn't enough.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "The page's full http(s) address."}},
            "required": ["url"]}}},
]


def base_url():
    return str(cfg.setting("narwhal", "search_url", "http://192.168.1.138:8888") or "").rstrip("/")


def search(query, n=MAX_RESULTS, opener=urllib.request.urlopen):
    """[{title, url, content}] from SearXNG."""
    q = urllib.parse.urlencode({"q": str(query)[:300], "format": "json"})
    req = urllib.request.Request(f"{base_url()}/search?{q}", headers={"User-Agent": UA})
    with opener(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read(2_000_000).decode("utf-8", "replace"))
    out = []
    for item in data.get("results") or []:
        url = item.get("url")
        if url and url not in {o["url"] for o in out}:
            out.append({"title": str(item.get("title") or "")[:200], "url": str(url)[:500],
                        "content": " ".join(str(item.get("content") or "").split())[:400]})
        if len(out) >= n:
            break
    return out


def _public(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            return False
    return bool(infos)


def page_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def open_page(url, opener=urllib.request.urlopen, public=_public):
    u = urllib.parse.urlparse(str(url))
    if u.scheme not in ("http", "https") or not u.hostname:
        return "Only http(s) addresses can be opened."
    if not public(u.hostname):
        return "That address isn't on the public internet, so it can't be opened."
    req = urllib.request.Request(u.geturl(), headers={"User-Agent": UA})
    with opener(req, timeout=TIMEOUT) as r:
        kind = r.headers.get("Content-Type", "") if getattr(r, "headers", None) else ""
        body = r.read(1_500_000).decode("utf-8", "replace")
    text = page_text(body) if "html" in kind or "<html" in body[:500].lower() else body
    return text[:PAGE_CHARS] + ("\n[…cut]" if len(text) > PAGE_CHARS else "")


def run(name, args):
    """(step line for the apps, result text for the model) for one tool call."""
    try:
        args = json.loads(args) if isinstance(args, str) else (args or {})
    except ValueError:
        args = {}
    try:
        if name == "web_search":
            q = str(args.get("query") or "").strip()
            if not q:
                return "▸ Search  (empty)", "No query given."
            hits = search(q)
            body = "\n\n".join(f"[{i + 1}] {h['title']}\n{h['url']}\n{h['content']}" for i, h in enumerate(hits))
            return f"▸ Search  {q}", body or "No results."
        if name == "open_page":
            url = str(args.get("url") or "").strip()
            return f"▸ Open  {url[:160]}", open_page(url)
    except Exception as e:  # noqa: BLE001 - the model is told, and can try something else
        return f"▸ {name}  failed: {e}"[:200], f"That didn't work: {e}"
    return f"▸ {name}  (unknown tool)", "No such tool."
