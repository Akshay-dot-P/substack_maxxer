"""
End-to-end orchestrator. No local database at any stage:

  discover URLs -> enrich each into a SubstackPost (in memory)
  -> rank articles by engagement -> rank+judge passages
  -> synthesize final essay
  -> write to Google Sheets (durable/reviewable record)
  -> append to docs/data.json (what the GitHub Pages site actually reads)

Nothing is cached to disk between stages; a run is stateless except for
its two output side effects (Sheets row, data.json entry). Re-running the
same query just does the work again -- fine at this scale, and it means
there's no cache-invalidation logic to get wrong.

Usage:
    python pipeline.py "how to get into flow state"
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import config
import discovery
import judge
import ranking
import sheets_writer
from substack_client import SubstackClient


def run(query: str) -> "judge.SynthesisResult":
    print(f'\n=== Running pipeline for: "{query}" ===\n')
    client = SubstackClient()

    print("[1/5] Discovering candidate posts...")
    urls = discovery.discover(query, client)
    if not urls:
        raise RuntimeError(
            "No candidate URLs found. Try a broader query, or check that "
            "ddgs isn't currently rate-limited (see README troubleshooting)."
        )

    print(f"[2/5] Enriching {len(urls)} candidate posts (this is the slow step)...")
    posts = []
    for i, url in enumerate(urls, 1):
        post = client.get_post_by_url(url)
        if post:
            posts.append(post)
        print(f"  ...{i}/{len(urls)}", end="\r")
    print()

    print("[3/5] Ranking articles by engagement, then passages by relevance...")
    ranked_articles = ranking.rank_articles(posts)
    if not ranked_articles:
        raise RuntimeError("No usable (free, non-empty) articles found among candidates.")
    candidate_passages = ranking.rank_all_passages(query, ranked_articles)

    print(f"[4/5] Judging {len(candidate_passages)} candidate passages with the LLM...")
    judged_passages = judge.judge_passages(query, candidate_passages)
    final_passages = judged_passages[: config.FINAL_PASSAGES]

    print("[5/5] Synthesizing final article...")
    result = judge.synthesize_article(query, final_passages)

    _write_outputs(result, final_passages)
    return result


def _write_outputs(result, final_passages) -> None:
    sheets_writer.write_run(result, final_passages)
    _append_to_site_data(result)


def _append_to_site_data(result) -> None:
    """Prepend this run to docs/data.json (newest first), creating it if needed."""
    site_dir = Path(config.SITE_DIR)
    site_dir.mkdir(parents=True, exist_ok=True)
    data_path = site_dir / config.SITE_DATA_FILE

    existing = []
    if data_path.exists():
        try:
            existing = json.loads(data_path.read_text())
        except json.JSONDecodeError:
            print(f"[pipeline] warning: {data_path} was not valid JSON, starting fresh")

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": result.query,
        "title": result.title,
        "body_markdown": result.body_markdown,
        "sources": result.sources,
    }
    existing.insert(0, entry)

    data_path.write_text(json.dumps(existing, indent=2))
    print(f"[pipeline] wrote {data_path} ({len(existing)} total entries)")


if __name__ == "__main__":
    query_arg = " ".join(sys.argv[1:]).strip()
    if not query_arg:
        query_arg = input("Topic to search Substack for: ").strip()

    final_result = run(query_arg)
    print("\n" + "=" * 60)
    print(final_result.body_markdown)
    print("=" * 60)
