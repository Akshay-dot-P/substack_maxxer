"""
Shared data models for the Substack discovery/synthesis pipeline.

Kept as plain dataclasses (no ORM/pydantic) so every module can pass
these around and json.dumps(asdict(x)) them for caching/debugging without
extra dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SubstackPost:
    """A single post pulled from a publication's unofficial JSON API."""

    url: str                       # canonical post URL, e.g. https://pub.substack.com/p/slug
    domain: str                    # e.g. "pub.substack.com" or a custom domain
    slug: str
    title: str = ""
    subtitle: str = ""
    author: str = ""
    publication_name: str = ""
    published_at: Optional[str] = None
    like_count: int = 0
    comment_count: int = 0
    restack_count: int = 0
    word_count: int = 0
    is_paid: bool = False          # True if this is a paywalled post
    html: str = ""                 # raw post body HTML (free portion only)
    text: str = ""                 # cleaned plaintext, populated after parsing

    @property
    def engagement_raw(self) -> dict:
        return {
            "likes": self.like_count,
            "comments": self.comment_count,
            "restacks": self.restack_count,
        }


@dataclass
class RankedArticle:
    """A SubstackPost plus its computed engagement score, in ranked order."""

    post: SubstackPost
    engagement_score: float


@dataclass
class RankedPassage:
    """A chunk of text from one article plus its similarity + LLM judge scores."""

    post: SubstackPost
    text: str
    embedding_score: float = 0.0
    llm_score: float = 0.0
    llm_reason: str = ""
    combined_score: float = 0.0


@dataclass
class SynthesisResult:
    """Final compiled output handed back to the CLI / caller."""

    query: str
    title: str
    body_markdown: str
    sources: list = field(default_factory=list)   # list[dict]: {title, author, url}
