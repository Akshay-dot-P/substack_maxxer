"""
Discovery layer.

Substack has no public endpoint that full-text-searches post content across
the whole platform -- /api/v1/publication/search only matches publication
*names/descriptions*, not what's written inside individual posts. So we
combine two independent discovery strategies and de-dupe the results:

  1. web_search_discovery(): site-restricted web search (via `ddgs`, free,
     no API key) for `site:substack.com <query>`. This is doing the actual
     full-text discovery work, using a real search engine's index instead
     of Substack's.

  2. publication_discovery(): ask Substack's own publication search for
     newsletters plausibly about the topic, then pull each one's
     *top-sorted* archive (i.e. already engagement-ranked by Substack
     itself). Topical relevance is filtered later, on full text, in
     ranking.py -- this stage just catches well-regarded posts in
     relevant niches that a general web search might rank low.

Both return plain post URLs; substack_client.py does the actual enrichment
(full text + engagement counts) afterward. Keeping discovery URL-only means
you can swap in a paid SERP API later (Google Custom Search, SerpAPI, Bing)
by writing one function with the same signature as web_search_discovery().
"""
from __future__ import annotations

import re
from typing import Optional

import config
from substack_client import SubstackClient

POST_URL_RE = re.compile(r"https?://[^/\s]+\.substack\.com/p/[^\s?#]+|https?://[^/\s]+/p/[^\s?#]+")


def web_search_discovery(query: str, max_results: int = config.DISCOVERY_WEB_RESULTS) -> list[str]:
    """Site-restricted web search for Substack posts about `query`.

    Uses the free `ddgs` (formerly duckduckgo_search) package. No API key
    needed, but DuckDuckGo will rate-limit aggressive use -- this is meant
    for occasional personal runs, not a production crawler. Swap this
    function out for Google Custom Search / SerpAPI if you need higher
    volume or more reliable uptime.
    """
    try:
        from ddgs import DDGS
    except ImportError as e:
        raise ImportError(
            "ddgs not installed. Run: pip install ddgs --break-system-packages"
        ) from e

    urls: list[str] = []
    search_query = f'site:substack.com "{query}"'
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(search_query, max_results=max_results):
                href = r.get("href") or r.get("url", "")
                if POST_URL_RE.match(href):
                    urls.append(href)
    except Exception as e:  # ddgs raises its own exception types; broad catch is intentional here
        print(f"[discovery] web search failed ({e}); continuing with 0 web results")

    return list(dict.fromkeys(urls))  # de-dupe, preserve order


def publication_discovery(
    query: str,
    client: SubstackClient,
    max_pubs: int = config.DISCOVERY_PUBS_TO_CHECK,
    posts_per_pub: int = config.DISCOVERY_POSTS_PER_PUB,
) -> list[str]:
    """Find relevant publications, then pull each one's top-sorted archive.

    No keyword pre-filter here on purpose: substack-api's get_posts() only
    returns lightweight Post shells (url + slug), not the archive-level
    title/subtitle, so there's nothing cheap to filter on at this stage.
    We lean on Substack's own "top" sort (already engagement-ranked within
    that newsletter) to keep this bounded, and let ranking.py's embedding
    step do the actual topical relevance filtering once we have full text.

    This means max_pubs * posts_per_pub full post fetches -- keep both
    numbers modest (defaults: 5 pubs x 5 posts = 25 fetches) for a
    personal-scale run; each fetch is a separate HTTP call.
    """
    urls: list[str] = []

    pubs = client.search_publications(query, limit=max_pubs)
    for pub in pubs:
        domain = pub.get("subdomain") or pub.get("custom_domain")
        if not domain:
            continue
        if "." not in domain:
            domain = f"{domain}.substack.com"

        archive_posts = client.get_archive(domain, sort="top", limit=posts_per_pub)
        urls.extend(p.url for p in archive_posts if getattr(p, "url", None))

    return list(dict.fromkeys(urls))


def discover(query: str, client: Optional[SubstackClient] = None) -> list[str]:
    """Run both discovery strategies and return a de-duplicated URL list."""
    client = client or SubstackClient()

    web_urls = web_search_discovery(query)
    pub_urls = publication_discovery(query, client)

    combined = list(dict.fromkeys(web_urls + pub_urls))
    print(
        f"[discovery] {len(web_urls)} via web search, {len(pub_urls)} via "
        f"publication search, {len(combined)} unique total"
    )
    return combined
