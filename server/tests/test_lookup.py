"""Web search parsing, and reading only public pages."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process.tools import lookup

SEARCH_PAGE = """
<div class="result results_links web-result result--ad"><div class="links_main">
<a rel="nofollow" class="result__a" href="https://ads.example/">An advert</a>
<a class="result__snippet" href="x">Buy now</a><div class="clear"></div></div></div>
<div class="result results_links web-result "><div class="links_main">
<h2 class="result__title"><a rel="nofollow" class="result__a"
 href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fpage&amp;rut=1">Example &amp; <b>page</b></a></h2>
<a class="result__snippet" href="x">The <b>first</b> real one.</a><div class="clear"></div></div></div>
<div class="result results_links web-result "><div class="links_main">
<a rel="nofollow" class="result__a" href="https://two.example/">Second</a>
<div class="clear"></div></div></div>
"""


def test_search_skips_adverts_and_unwraps_redirects():
    hits = lookup.parse_results(SEARCH_PAGE, 5)
    assert [h["title"] for h in hits] == ["Example & page", "Second"]
    assert hits[0]["url"] == "https://example.org/page"
    assert hits[0]["snippet"] == "The first real one."
    assert hits[1]["snippet"] == ""
    assert len(lookup.parse_results(SEARCH_PAGE, 1)) == 1


def test_page_text_drops_scripts_and_menus():
    title, text = lookup.page_text(
        "<html><head><title> Hi </title><script>var x=1</script></head><body>"
        "<nav>Home | About</nav><h1>Heading</h1><p>Some   text.</p>"
        "<footer>(c) 2026</footer></body></html>")
    assert title == "Hi"
    assert text == "Heading\nSome text."


def test_private_addresses_are_not_fetched(monkeypatch):
    def no_fetch(*a, **k):
        raise AssertionError("fetched a private address")
    monkeypatch.setattr(lookup, "_get", no_fetch)
    for url in ("http://127.0.0.1:8765/reset", "http://192.168.1.1/",
                "http://localhost/", "http://[::1]/", "file:///etc/passwd"):
        assert "can't be read" in lookup.read_page(url) or "Only http" in lookup.read_page(url)
