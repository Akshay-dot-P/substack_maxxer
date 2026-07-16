"""
Shared data models for the Substack discovery/synthesis pipeline.

Plain dataclasses, not pydantic -- there's no external API surface here
that needs schema validation/OpenAPI generation, just data moving between
modules in one process. That tradeoff does mean nothing validates field
types at construction time, so SubstackPost defends itself in
__post_init__ against the one failure mode that actually bites: negative
counts from Substack's undocumented API reaching ranking.py's
math.log1p(), which throws on inputs <= -1.

to_dict() methods exist on the two models that get serialized externally
(to Google Sheets, to docs/data.json) specifically so the field list lives
in ONE place. Without them, sheets_writer.py and pipeline.py would each
hand-list the same fields as separate, easy-to-desync lists -- add a field
to SynthesisResult and forget to update one of the two copies, and you get
silently misaligned spreadsheet columns instead of an error.
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

    def __post_init__(self) -> None:
        # Defensive clamp: these come from an undocumented, unvalidated API.
        # A negative value here would crash ranking.engagement_score()'s
        # math.log1p() call for this post's entire batch, not just skip it.
        self.like_count = max(0, self.like_count)
        self.comment_count = max(0, self.comment_count)
        self.restack_count = max(0, self.restack_count)
        self.word_count = max(0, self.word_count)


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

    def to_dict(self) -> dict:
        """Flat view for spreadsheet rows. Rounds scores for readability in Sheets."""
        return {
            "source_title": self.post.title,
            "source_author": self.post.author,
            "source_url": self.post.url,
            "passage_text": self.text,
            "embedding_score": round(self.embedding_score, 4),
            "llm_score": round(self.llm_score, 4),
            "combined_score": round(self.combined_score, 4),
            "llm_reason": self.llm_reason,
        }


@dataclass
class SynthesisResult:
    """Final compiled output handed back to the CLI / caller."""

    query: str
    title: str
    body_markdown: str
    sources: list = field(default_factory=list)   # list[dict]: {title, author, url}

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "title": self.title,
            "body_markdown": self.body_markdown,
            "sources": self.sources,
        }
