"""
Client for talking to Substack.

Design decision (v2): instead of hand-rolling requests calls against
Substack's undocumented endpoints, this wraps `substack-api`
(pip install substack-api, github.com/NHagar/substack_api) for the actual
HTTP work. That package already handles pagination, retries, and
rate-limit-friendly delays -- reinventing that badly would just add bugs.

What we still own on top of it:
  - Converting its raw dicts into our own SubstackPost dataclass, with
    defensive extraction since engagement-count field names aren't
    documented for the /posts/{slug} endpoint specifically (they ARE
    confirmed elsewhere in Substack's API family -- e.g. their chat/notes
    endpoints use "reaction_count" and "comment_count" -- so those are our
    first-choice keys, with fallbacks after).
  - Publication search (find newsletters about a topic), which the
    substack-api package only uses internally to resolve a *known*
    newsletter's ID -- it doesn't expose "search newsletters by topic" as
    a public method, so we call that one endpoint directly ourselves.
"""
from __future__ import annotations

import time
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from substack_api import Newsletter, Post

import config
from models import SubstackPost

FIELD_CANDIDATES = {
    "like_count": ["reaction_count", "reactions", "like_count"],
    "comment_count": ["comment_count", "comments_count"],
    "restack_count": ["restacks", "restacked_count", "restack_count"],
    "word_count": ["wordcount", "word_count"],
    "author": ["author", "byline", "publishedBylines"],
}

PUBLICATION_SEARCH_URL = "https://substack.com/api/v1/publication/search"


def _first_present(d: dict, keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            val = d[k]
            if isinstance(val, dict):  # e.g. {"❤": 12, "👍": 3}
                try:
                    return sum(int(v) for v in val.values())
                except (TypeError, ValueError):
                    continue
            return val
    return default


class SubstackClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
        )

    # -- publication discovery (not covered by substack-api's public API) --
    def search_publications(self, query: str, limit: int = 10) -> list[dict]:
        """Find newsletters whose name/description matches `query`.

        Confirmed response shape (verified against substack-api's source,
        which relies on this same endpoint internally):
            {"publications": [{"id", "subdomain", "custom_domain", "name", ...}]}
        """
        try:
            resp = self.session.get(
                PUBLICATION_SEARCH_URL,
                params={"query": query, "page": 0, "limit": limit, "sort": "relevance"},
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            return resp.json().get("publications", [])
        except requests.RequestException as e:
            print(f"[substack_client] publication search failed: {e}")
            return []
        finally:
            time.sleep(config.REQUEST_DELAY_SECONDS)

    # -- per-newsletter archive, via substack-api ------------------------
    def get_archive(self, domain: str, sort: str = "top", limit: int = 20) -> list[Post]:
        """Return Post objects for one newsletter, sorted by engagement ('top') or date ('new')."""
        try:
            newsletter = Newsletter(f"https://{domain}")
            return newsletter.get_posts(sorting=sort, limit=limit)
        except Exception as e:
            print(f"[substack_client] archive fetch failed for {domain}: {e}")
            return []

    # -- single post enrichment ------------------------------------------
    def get_post_by_url(self, post_url: str) -> Optional[SubstackPost]:
        """Fetch full metadata + content for one post URL, mapped to our SubstackPost."""
        try:
            post = Post(post_url)
            raw = post.get_metadata()
        except Exception as e:
            print(f"[substack_client] failed to fetch {post_url}: {e}")
            return None
        return self._to_our_post(raw, post)

    def _to_our_post(self, raw: dict, post_obj: Post) -> SubstackPost:
        html = raw.get("body_html", "") or ""
        author = _first_present(raw, FIELD_CANDIDATES["author"], default="")
        if isinstance(author, list) and author:
            author = author[0].get("name", "") if isinstance(author[0], dict) else str(author[0])

        domain = urlparse(post_obj.url).netloc

        return SubstackPost(
            url=raw.get("canonical_url", post_obj.url),
            domain=domain,
            slug=post_obj.slug or "",
            title=raw.get("title", ""),
            subtitle=raw.get("subtitle", ""),
            author=author or "",
            publication_name=raw.get("publication_name", ""),
            published_at=raw.get("post_date"),
            like_count=int(_first_present(raw, FIELD_CANDIDATES["like_count"], default=0) or 0),
            comment_count=int(_first_present(raw, FIELD_CANDIDATES["comment_count"], default=0) or 0),
            restack_count=int(_first_present(raw, FIELD_CANDIDATES["restack_count"], default=0) or 0),
            word_count=int(_first_present(raw, FIELD_CANDIDATES["word_count"], default=0) or 0),
            is_paid=(raw.get("audience") == "only_paid"),
            html=html,
            text=self._html_to_text(html),
        )

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Strip a post's HTML body to clean paragraph text, one paragraph per line."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all(["p", "li", "h2", "h3"])]
        return "\n\n".join(p for p in paragraphs if p)
