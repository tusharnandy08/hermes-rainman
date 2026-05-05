"""News Fetcher — retrieves relevant headlines for a market question.

Uses Google News RSS (no auth, no extra deps beyond httpx + stdlib xml).
Falls back gracefully if results are empty.
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote_plus
import httpx


@dataclass
class NewsItem:
    title: str
    description: str
    source: str
    published: str
    url: str

    def to_context_str(self) -> str:
        """Single-line string suitable for LLM context."""
        desc = self.description[:200].replace("\n", " ") if self.description else ""
        return f"[{self.published[:16]}] {self.source}: {self.title}. {desc}"


class NewsFetcher:
    """Fetches recent news headlines for a given search query."""

    GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    TIMEOUT = 12.0

    def __init__(self):
        self._client = httpx.Client(
            timeout=self.TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; prediction-bot/2.0; "
                    "+https://github.com/tusharnandy08/hermes-rainman)"
                )
            },
            follow_redirects=True,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    def close(self):
        self._client.close()

    def fetch(self, query: str, max_results: int = 8) -> list[NewsItem]:
        """Fetch top news items for query. Returns empty list on failure."""
        url = self.GOOGLE_NEWS_RSS.format(q=quote_plus(query))
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
            return self._parse_rss(resp.text, max_results)
        except Exception as exc:
            # Graceful degradation — analyst will note "no news found"
            print(f"[news_fetcher] warn: {exc}")
            return []

    def fetch_for_market(self, market_title: str, max_results: int = 8) -> list[NewsItem]:
        """Convenience: build a good query from a market title."""
        # Strip common prediction market boilerplate
        import re
        query = market_title
        query = re.sub(r'\b(will|by end of|before|in \d{4})\b', '', query, flags=re.I)
        query = re.sub(r'\s+', ' ', query).strip()
        # Use up to 8 words
        words = query.split()
        query = " ".join(words[:8])
        return self.fetch(query, max_results=max_results)

    @staticmethod
    def _parse_rss(xml_text: str, max_results: int) -> list[NewsItem]:
        """Parse Google News RSS XML into NewsItem list."""
        items: list[NewsItem] = []
        try:
            # Google News RSS sometimes has namespace issues — strip namespaces
            xml_text = xml_text.replace(' xmlns="', ' xmlnsfoo="')
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return items

        channel = root.find("channel")
        if channel is None:
            return items

        for item_el in channel.findall("item")[:max_results]:
            def txt(tag: str) -> str:
                el = item_el.find(tag)
                return (el.text or "").strip() if el is not None else ""

            # Source may be in <source> or in the title like "Title - Source"
            source_el = item_el.find("source")
            if source_el is not None:
                source = (source_el.text or "").strip()
            else:
                raw_title = txt("title")
                if " - " in raw_title:
                    source = raw_title.rsplit(" - ", 1)[-1]
                else:
                    source = "Unknown"

            title = txt("title")
            if " - " in title:
                title = title.rsplit(" - ", 1)[0].strip()

            items.append(NewsItem(
                title=title,
                description=_strip_html(txt("description")),
                source=source,
                published=txt("pubDate"),
                url=txt("link"),
            ))

        return items


def _strip_html(text: str) -> str:
    """Very simple HTML tag stripper."""
    import re
    return re.sub(r'<[^>]+>', '', text).strip()
