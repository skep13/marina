"""Finding things out: searching the web, reading a page, the weather.

These work on any bridge, Mac or server, and need no API key: search goes
through DuckDuckGo's HTML page and the weather through Open-Meteo.

read_page only fetches public addresses. Without that, "read
http://192.168.1.1" would let her (or someone talking her into it) poke at
the router or anything else on the home network the bridge can reach.
"""
import ipaddress
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from process.config import setting

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
TIMEOUT = 12
PAGE_CHARS = 6000
MAX_BYTES = 3_000_000
MAX_REDIRECTS = 5


def _get(url, **kw):
    return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, **kw)


# --- search -----------------------------------------------------------------

_RESULT = re.compile(
    r'<div (class="[^"]*\bresult\b[^"]*">.*?)<div class="clear">', re.S)
_TITLE = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)
_TAGS = re.compile(r"<[^>]+>")


def _plain(fragment):
    return " ".join(unescape(_TAGS.sub("", fragment)).split())


def _real_link(href):
    """DuckDuckGo sometimes wraps results in its own redirect."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        return parse_qs(parsed.query).get("uddg", [href])[0]
    return href


def parse_results(page, limit):
    results = []
    for block in _RESULT.findall(page):
        if "result--ad" in block or "badge--ad" in block:
            continue
        title = _TITLE.search(block)
        if not title:
            continue
        snippet = _SNIPPET.search(block)
        results.append({
            "title": _plain(title.group(2)),
            "url": _real_link(unescape(title.group(1))),
            "snippet": _plain(snippet.group(1)) if snippet else "",
        })
        if len(results) >= limit:
            break
    return results


def web_search(query, max_results=5):
    query = " ".join((query or "").split())
    if not query:
        return "Search for what?"
    try:
        limit = max(1, min(int(max_results), 10))
    except (TypeError, ValueError):
        limit = 5
    try:
        r = requests.post("https://html.duckduckgo.com/html/", data={"q": query},
                          headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        return f"The search didn't go through: {e}"
    results = parse_results(r.text, limit)
    print(f"[tool] searched for {query!r}: {len(results)} results", flush=True)
    if not results:
        return f"Nothing came up for {query!r}."
    lines = [f"Results for {query!r}:"]
    for i, hit in enumerate(results, 1):
        lines.append(f"{i}. {hit['title']}\n   {hit['url']}"
                     + (f"\n   {hit['snippet']}" if hit["snippet"] else ""))
    lines.append("Read a result with read_page before relying on more than its snippet.")
    return "\n".join(lines)


# --- reading a page ---------------------------------------------------------

def _public(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


class _Text(HTMLParser):
    """The readable text of a page, skipping scripts, menus and footers."""
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header",
            "aside", "form", "iframe", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
             "section", "article", "pre", "blockquote", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipping = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skipping:
            self.parts.append(data)

    def text(self):
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def page_text(html):
    parser = _Text()
    parser.feed(html)
    return " ".join(parser.title.split()), parser.text()


def read_page(url):
    url = (url or "").strip()
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return "Only http and https pages can be read."
        if not _public(parsed.hostname):
            return "That address is on a private network, so it can't be read."
        try:
            r = _get(url, allow_redirects=False, stream=True)
        except requests.RequestException as e:
            return f"Couldn't load it: {e}"
        if r.is_redirect and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            r.close()
            continue
        break
    else:
        return "That page redirects too many times."

    if r.status_code >= 400:
        return f"The page answered with an error ({r.status_code})."
    kind = r.headers.get("content-type", "")
    if not any(t in kind for t in ("html", "text/plain", "json", "xml")):
        return f"That isn't a page she can read ({kind or 'unknown type'})."
    body = r.raw.read(MAX_BYTES, decode_content=True)
    r.close()
    text = body.decode(r.encoding or "utf-8", errors="replace")
    title, content = page_text(text) if "html" in kind else ("", text.strip())
    if not content:
        return "The page had no readable text. It may need JavaScript."
    if len(content) > PAGE_CHARS:
        content = content[:PAGE_CHARS] + "\n… (the rest is cut off)"
    print(f"[tool] read {urlparse(url).netloc} ({len(content)} chars)", flush=True)
    return f"{title or url}\n{url}\n\n{content}"


# --- weather ----------------------------------------------------------------

_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy with rime", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "heavy snow showers", 95: "thunderstorms",
    96: "thunderstorms with hail", 99: "thunderstorms with hail",
}


def _place(name):
    r = _get("https://geocoding-api.open-meteo.com/v1/search",
             params={"name": name, "count": 1})
    r.raise_for_status()
    hits = r.json().get("results") or []
    if not hits:
        return None
    hit = hits[0]
    label = ", ".join(p for p in (hit.get("name"), hit.get("admin1"), hit.get("country")) if p)
    return hit["latitude"], hit["longitude"], label


def weather(place="", days=1):
    place = (place or "").strip() or str(setting("weather", "location", "") or "")
    if not place:
        return ("No place to check: ask them where they are, or set "
                "weather.location in the config.")
    try:
        days = max(1, min(int(days), 7))
    except (TypeError, ValueError):
        days = 1
    metric = str(setting("weather", "units", "metric")) != "imperial"
    try:
        found = _place(place)
        if not found:
            return f"Couldn't find a place called {place!r}."
        lat, lon, label = found
        r = _get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "timezone": "auto",
            "forecast_days": days,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max",
            "temperature_unit": "celsius" if metric else "fahrenheit",
            "wind_speed_unit": "kmh" if metric else "mph",
        })
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError, KeyError) as e:
        return f"Couldn't get the weather: {e}"

    deg = "°C" if metric else "°F"
    speed = "km/h" if metric else "mph"
    now = data.get("current") or {}
    lines = [f"Weather for {label}:"]
    if now:
        lines.append(
            f"Now: {_CODES.get(now.get('weather_code'), 'unknown')}, "
            f"{round(now['temperature_2m'])}{deg} (feels like "
            f"{round(now['apparent_temperature'])}{deg}), wind "
            f"{round(now['wind_speed_10m'])} {speed}.")
    daily = data.get("daily") or {}
    for i, day in enumerate(daily.get("time") or []):
        rain = (daily.get("precipitation_probability_max") or [None])[i]
        lines.append(
            f"{day}: {_CODES.get(daily['weather_code'][i], 'unknown')}, "
            f"{round(daily['temperature_2m_min'][i])} to "
            f"{round(daily['temperature_2m_max'][i])}{deg}"
            + (f", {rain}% chance of rain" if rain is not None else "") + ".")
    print(f"[tool] weather for {label}", flush=True)
    return "\n".join(lines)


SPECS = [
    ("web_search", web_search, "web", {
        "description": "Search the web. Use it for anything current or that you "
                       "aren't sure of: news, prices, release dates, opening times, "
                       "an error message they're stuck on. Don't guess at facts you "
                       "could look up. Returns titles, links and snippets.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "description": "1 to 10, default 5."}},
            "required": ["query"]}}),
    ("read_page", read_page, "web", {
        "description": "Read the text of a web page, from a search result or a "
                       "link they gave you. Long pages are cut off.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}}, "required": ["url"]}}),
    ("weather", weather, "weather", {
        "description": "The weather now and the forecast. Leave place empty for "
                       "where they live, if that's set.",
        "parameters": {"type": "object", "properties": {
            "place": {"type": "string", "description": "A town or city."},
            "days": {"type": "integer", "description": "Days of forecast, 1 to 7."}}}}),
]
