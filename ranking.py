"""
Two separate ranking passes:

1. rank_articles(): sorts whole posts by engagement (likes/comments/
   restacks), so we know which articles are worth extracting passages
   from at all.

2. rank_passages(): within the top articles, chunks the text and ranks
   chunks by embedding similarity to the search query, so we know which
   *parts* of each article are actually relevant before spending an LLM
   call judging them.

No database, no vector store -- everything here is in-memory numpy. At
personal-project scale (a handful of articles, a few dozen chunks) that's
plenty fast and keeps the whole pipeline stateless between runs.
"""
from __future__ import annotations

import math
import re
from typing import Optional

import numpy as np

import config
from models import RankedArticle, RankedPassage, SubstackPost

_embedder = None  # lazy-loaded singleton, see _get_embedder()


def _get_embedder():
    """Lazy-load the sentence-transformers model on first use.

    Lazy so that importing this module (e.g. from tests) doesn't force a
    model download / load if you're only testing the non-embedding parts.
    """
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(config.EMBEDDING_MODEL)
    return _embedder


# --- article-level ranking ---------------------------------------------
def engagement_score(post: SubstackPost) -> float:
    """Weighted, log-dampened engagement score.

    log1p dampening matters here: without it, one viral 5,000-like post
    would completely drown out five solid 200-like posts, and you'd end up
    synthesizing from a single article instead of a genuine cross-section.
    Restacks are weighted highest since they're the strongest signal
    (someone chose to actively re-share it), likes weakest.
    """
    w = config.ENGAGEMENT_WEIGHTS
    raw = (
        w["likes"] * post.like_count
        + w["comments"] * post.comment_count
        + w["restacks"] * post.restack_count
    )
    return math.log1p(raw)


def rank_articles(posts: list[SubstackPost], top_n: int = config.TOP_ARTICLES) -> list[RankedArticle]:
    """Sort posts by engagement score, drop paywalled/empty ones, keep top_n."""
    usable = [p for p in posts if p.text and not p.is_paid]
    ranked = sorted(
        (RankedArticle(post=p, engagement_score=engagement_score(p)) for p in usable),
        key=lambda r: r.engagement_score,
        reverse=True,
    )
    return ranked[:top_n]


# --- passage-level ranking -----------------------------------------------
def chunk_text(text: str, min_words: int = 15, max_words: int = 80) -> list[str]:
    """Split cleaned article text into paragraph-sized chunks.

    substack_client._html_to_text() already emits one paragraph per line
    (joined by "\\n\\n"), so we start from that. Paragraphs shorter than
    min_words get merged into the next one (a lone one-line paragraph is
    rarely a self-contained "best line"); paragraphs longer than max_words
    get split on sentence boundaries so a single giant paragraph doesn't
    dominate purely by being long.
    """
    raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buffer = ""

    for para in raw_paragraphs:
        word_count = len(para.split())
        if word_count > max_words:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sentence_buffer = ""
            for sent in sentences:
                candidate = (sentence_buffer + " " + sent).strip()
                if len(candidate.split()) > max_words and sentence_buffer:
                    chunks.append(sentence_buffer.strip())
                    sentence_buffer = sent
                else:
                    sentence_buffer = candidate
            if sentence_buffer:
                buffer = sentence_buffer  # carries into merge logic below
        else:
            buffer = (buffer + " " + para).strip() if buffer else para

        if len(buffer.split()) >= min_words:
            chunks.append(buffer)
            buffer = ""

    if buffer and len(buffer.split()) >= 5:  # keep a short tail rather than drop it
        chunks.append(buffer)

    return chunks


def rank_passages_for_article(
    query: str, article: RankedArticle, top_k: int = config.PASSAGES_PER_ARTICLE
) -> list[RankedPassage]:
    """Chunk one article and rank its chunks by cosine similarity to the query."""
    chunks = chunk_text(article.post.text)
    if not chunks:
        return []

    embedder = _get_embedder()
    query_vec = embedder.encode([query], normalize_embeddings=True)[0]
    chunk_vecs = embedder.encode(chunks, normalize_embeddings=True)

    sims = chunk_vecs @ query_vec  # cosine similarity, since both are normalized
    order = np.argsort(-sims)[:top_k]

    return [
        RankedPassage(post=article.post, text=chunks[i], embedding_score=float(sims[i]))
        for i in order
    ]


def rank_all_passages(query: str, articles: list[RankedArticle]) -> list[RankedPassage]:
    """Run rank_passages_for_article across every top-ranked article."""
    passages: list[RankedPassage] = []
    for article in articles:
        passages.extend(rank_passages_for_article(query, article))
    return passages
