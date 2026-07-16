"""
Two Groq calls:

1. judge_passages(): given the embedding-shortlisted passages, ask the LLM
   to actually judge which lines are good -- insightful, self-contained,
   quotable -- rather than just "similar to the query". Embedding
   similarity finds *relevant* text; it doesn't know good writing from
   filler. This is one batched call (all candidates at once) rather than
   one call per passage, to keep API usage sane.

2. synthesize_article(): compiles the final judged passages into one
   article. The prompt bakes in hard editorial rules -- mostly paraphrase,
   short attributed quotes only, always link back to the source -- because
   a "compiled article" that's mostly other people's paragraphs stitched
   together is a real copyright problem for whatever you publish, not a
   hypothetical one.
"""
from __future__ import annotations

import json
import re

from groq import Groq

import config
from models import RankedPassage, SynthesisResult

JUDGE_SYSTEM_PROMPT = """You are an editor selecting the best passages from candidate excerpts \
for an essay on a given topic. For each candidate, score 1-10 on:
- Insight: does it say something specific and non-obvious, not generic advice?
- Self-containment: does it make sense as a standalone line, without needing the surrounding paragraph?
- Quotability: is it well-phrased, memorable, concrete (not vague or filler)?

Respond with ONLY a JSON array, no other text: \
[{"index": 0, "score": 7, "reason": "short reason"}, ...] \
covering every candidate index provided."""

SYNTHESIS_SYSTEM_PROMPT = """You are compiling a single essay on a topic, built from excerpts of \
several independent articles. Hard rules, no exceptions:
1. Mostly PARAPHRASE the ideas in your own words. Use at most ONE short direct quote (under 20 words) \
per source, and never more than one quote total from the same source.
2. Every idea you use must be attributed inline, e.g. "As [Author] argues in [linked post title]..." \
using the markdown link provided for that source.
3. Structure: a short intro framing the topic, 3-5 thematic sections (not one section per source -- \
group by IDEA, pulling from multiple sources per section where they overlap), and a brief closing thought.
4. End with a "## Sources" section listing every source used as a markdown link.
5. Do not invent facts, quotes, or attributions beyond what's given in the candidate passages."""


def _get_client() -> Groq:
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set (check your .env)")
    return Groq(api_key=config.GROQ_API_KEY)


def judge_passages(
    query: str, passages: list[RankedPassage], client: Groq | None = None
) -> list[RankedPassage]:
    """Score each candidate passage with the LLM, blend with embedding score, re-sort."""
    if not passages:
        return []
    client = client or _get_client()

    candidates_block = "\n".join(
        f'{i}. "{p.text}" (from: {p.post.title})' for i, p in enumerate(passages)
    )
    user_prompt = f'Topic: "{query}"\n\nCandidate excerpts:\n{candidates_block}'

    resp = client.chat.completions.create(
        model=config.GROQ_MODEL,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    scores = _parse_judge_response(resp.choices[0].message.content, len(passages))

    for i, p in enumerate(passages):
        llm_raw = scores.get(i, {"score": 5, "reason": ""})
        p.llm_score = llm_raw["score"] / 10.0
        p.llm_reason = llm_raw["reason"]
        # embedding_score is already 0-1 (cosine sim); blend 60/40 favoring LLM judgment,
        # since "is this a good line" is a quality call, not just a relevance call.
        p.combined_score = 0.6 * p.llm_score + 0.4 * p.embedding_score

    return sorted(passages, key=lambda p: p.combined_score, reverse=True)


def _parse_judge_response(raw_text: str, expected_count: int) -> dict:
    """Parse the judge's JSON array, tolerating minor formatting slop from the LLM."""
    match = re.search(r"\[.*\]", raw_text, re.DOTALL)
    if not match:
        print("[judge] could not find JSON array in judge response; defaulting all scores to 5")
        return {}
    try:
        parsed = json.loads(match.group(0))
        return {item["index"]: {"score": item.get("score", 5), "reason": item.get("reason", "")} for item in parsed}
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"[judge] failed to parse judge JSON ({e}); defaulting all scores to 5")
        return {}


def synthesize_article(
    query: str, passages: list[RankedPassage], client: Groq | None = None
) -> SynthesisResult:
    """Compile the final ranked passages into one attributed essay."""
    client = client or _get_client()

    sources = []
    seen_urls = set()
    for p in passages:
        if p.post.url not in seen_urls:
            sources.append({"title": p.post.title, "author": p.post.author, "url": p.post.url})
            seen_urls.add(p.post.url)

    passages_block = "\n\n".join(
        f'[{p.post.title} by {p.post.author or "unknown"}]({p.post.url})\nExcerpt: "{p.text}"'
        for p in passages
    )
    user_prompt = f'Topic: "{query}"\n\nSource excerpts to synthesize from:\n\n{passages_block}'

    resp = client.chat.completions.create(
        model=config.GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.5,
    )
    body_markdown = resp.choices[0].message.content

    title_match = re.search(r"^#\s*(.+)$", body_markdown, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else query.title()

    return SynthesisResult(query=query, title=title, body_markdown=body_markdown, sources=sources)
