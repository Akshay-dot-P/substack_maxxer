"""
Google Sheets as the "database".

No SQLite/Postgres/ChromaDB here on purpose -- Sheets gives you something
you can eyeball, manually edit, or delete rows from without touching code,
which matters if you want to review/curate before anything goes on the
public site. Two tabs:

  - "Articles": one row per pipeline run -- the final synthesized essay,
    plus a JSON blob of its sources. This is what the static site reads.
  - "Passages": one row per individual ranked passage that went into that
    run -- full audit trail (which article it came from, its embedding
    score, the LLM's judge score and reasoning). You don't need this for
    the site, but it's what you'd look at to tune the ranking weights.

Setup (see README): create a Google Cloud service account, download its
JSON key, share your target Sheet with the service account's email as an
Editor. No OAuth consent flow needed since this never touches a personal
Google account, just the one sheet you explicitly shared.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

import config
from models import RankedPassage, SynthesisResult

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

ARTICLES_HEADER = ["timestamp", "query", "title", "body_markdown", "sources_json"]
PASSAGES_HEADER = [
    "timestamp", "query", "source_title", "source_author", "source_url",
    "passage_text", "embedding_score", "llm_score", "combined_score", "llm_reason",
]


def _client() -> gspread.Client:
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return gspread.authorize(creds)


def _ensure_worksheet(spreadsheet: gspread.Spreadsheet, title: str, header: list[str]):
    try:
        ws = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(header))
        ws.append_row(header)
    return ws


def write_run(result: SynthesisResult, passages: list[RankedPassage]) -> None:
    """Append one run's results to the Articles and Passages tabs."""
    if not config.GOOGLE_SHEET_ID:
        print("[sheets_writer] GOOGLE_SHEET_ID not set -- skipping Sheets write")
        return

    gc = _client()
    spreadsheet = gc.open_by_key(config.GOOGLE_SHEET_ID)
    timestamp = datetime.now(timezone.utc).isoformat()

    articles_ws = _ensure_worksheet(spreadsheet, "Articles", ARTICLES_HEADER)
    articles_ws.append_row(
        [timestamp, result.query, result.title, result.body_markdown, json.dumps(result.sources)],
        value_input_option="RAW",
    )

    passages_ws = _ensure_worksheet(spreadsheet, "Passages", PASSAGES_HEADER)
    rows = [
        [
            timestamp, result.query, p.post.title, p.post.author, p.post.url,
            p.text, round(p.embedding_score, 4), round(p.llm_score, 4),
            round(p.combined_score, 4), p.llm_reason,
        ]
        for p in passages
    ]
    if rows:
        passages_ws.append_rows(rows, value_input_option="RAW")

    print(f"[sheets_writer] wrote 1 article + {len(rows)} passages to Sheet {config.GOOGLE_SHEET_ID}")
