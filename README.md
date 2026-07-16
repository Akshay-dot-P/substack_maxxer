# Commonplace — Substack synthesis pipeline

Search a topic, find the best Substack posts about it, extract the best
lines, and compile them into one attributed essay. No local database:
Google Sheets is the durable record, and the essay is published as a
static site on GitHub Pages.

```
 query
   │
   ▼
┌─────────────┐   ┌──────────────┐   ┌───────────────┐   ┌─────────────┐
│  discovery   │──▶│  enrichment  │──▶│    ranking     │──▶│    judge     │
│ web search + │   │ substack-api │   │ engagement +   │   │ Groq: score  │
│ pub search   │   │ (full text,  │   │ embedding      │   │ passages,    │
│ → post URLs  │   │  counts)     │   │ similarity     │   │ synthesize   │
└─────────────┘   └──────────────┘   └───────────────┘   └──────┬──────┘
                                                                   │
                                              ┌────────────────────┴───────────────────┐
                                              ▼                                        ▼
                                     Google Sheets                            docs/data.json
                                  (durable, editable                         (what GitHub Pages
                                   record of every run)                       actually serves)
```

## Why this shape

- **No database.** Every stage runs in memory; nothing is cached to disk
  between stages. A run is just: fetch → rank → judge → write two outputs.
- **Google Sheets instead of a database.** You can open it, read it, edit
  or delete a row, without touching code. That matters if you want to
  review a synthesis before it's public.
- **GitHub Pages instead of a server.** Pages only serves static files, so
  there's no backend to host or pay for. The pipeline runs elsewhere
  (your machine, or the included GitHub Action) and writes its result
  straight into `docs/data.json`, which the site reads client-side. The
  frontend never calls Groq, Substack, or Sheets directly — it can't,
  since those need secrets that must never ship to a page anyone can
  view-source.

## Setup

### 1. Install

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Groq (LLM judge + synthesis)

Get a key from console.groq.com, put it in `.env` as `GROQ_API_KEY`.

### 3. Google Sheets (the "database")

1. Go to [Google Cloud Console](https://console.cloud.google.com) → create
   a project (or reuse one) → enable the **Google Sheets API**.
2. **IAM & Admin → Service Accounts → Create Service Account.** No roles
   needed at the project level — access is granted per-sheet in step 4.
3. On the new service account: **Keys → Add Key → Create new key → JSON.**
   Save the downloaded file as `service_account.json` in the project root
   (it's already in `.gitignore` — never commit it).
4. Create a new Google Sheet (any name). Click **Share**, and share it
   with the service account's email (looks like
   `something@project-id.iam.gserviceaccount.com`, found in the JSON file
   or the Cloud Console) as an **Editor**.
5. Copy the Sheet's ID from its URL — `https://docs.google.com/spreadsheets/d/THIS_PART/edit`
   — into `.env` as `GOOGLE_SHEET_ID`.

The pipeline creates two tabs on first run: **Articles** (one row per
synthesis) and **Passages** (every ranked passage, for auditing/tuning).

### 4. GitHub Pages

Push this repo to GitHub, then: **Settings → Pages → Source: Deploy from
a branch → Branch: main, folder: /docs → Save.** Your site is live at
`https://<username>.github.io/<repo>/` within a minute or two. It'll show
the sample entry in `docs/data.json` until you run the pipeline for real.

### 5. (Optional) Automate with GitHub Actions

`.github/workflows/run_pipeline.yml` lets you trigger a run from the
Actions tab instead of your own machine — useful since it also commits
the updated `docs/data.json`, which auto-redeploys Pages. Add these repo
secrets (**Settings → Secrets and variables → Actions**):

- `GROQ_API_KEY`
- `GOOGLE_SHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON` — paste the **entire contents** of your
  `service_account.json` file as the secret value.

Then: **Actions tab → Run Substack synthesis pipeline → Run workflow**,
enter a topic, go.

## Running locally

```bash
python pipeline.py "how to get into flow state"
```

This is slow on purpose (rate-limited toward Substack) — expect a couple
of minutes for discovery + enrichment, plus a few Groq calls. Progress
prints to stdout as it goes.

## What each file does

- **`models.py`** — plain dataclasses passed between every stage
  (`SubstackPost`, `RankedArticle`, `RankedPassage`, `SynthesisResult`).
  No ORM, no database — just typed structure.
- **`config.py`** — every tunable knob, read from `.env`. Change ranking
  weights, how many articles/passages to keep, request delays, etc. here
  without touching logic.
- **`substack_client.py`** — talks to Substack. Wraps the maintained
  `substack-api` package (github.com/NHagar/substack_api) for the actual
  HTTP work (pagination, retries), and adds our own defensive field
  mapping on top since engagement-count field names (`reaction_count`,
  `comment_count`, ...) aren't formally documented — the extraction tries
  several known-plausible key names rather than assuming one exact shape.
- **`discovery.py`** — finds candidate post URLs two ways: a site-restricted
  web search (`site:substack.com <query>`, via the free `ddgs` package,
  since Substack has no endpoint that full-text-searches post content
  across the whole platform), and a publication-search-then-archive walk
  (find newsletters about the topic, pull their top-sorted posts).
- **`ranking.py`** — two passes: `rank_articles()` scores whole posts by
  engagement (restacks weighted highest, likes lowest, log-dampened so one
  viral post can't drown out everything else); `rank_passages_for_article()`
  chunks each article's text and ranks chunks by embedding similarity to
  your query (`sentence-transformers`, local, no API cost).
- **`judge.py`** — two Groq calls: `judge_passages()` has the LLM actually
  score passage *quality* (insight, self-containment, quotability — things
  embedding similarity can't tell you), blended 60/40 with the embedding
  score; `synthesize_article()` compiles the final passages into one essay
  under hard rules (mostly paraphrase, one short quote per source max,
  everything attributed and linked).
- **`sheets_writer.py`** — appends each run's result to your Google Sheet.
- **`pipeline.py`** — wires the above together end to end, then writes
  both outputs (Sheets row, `docs/data.json` entry).
- **`docs/`** — the static site. `index.html` + `style.css` + `app.js`,
  no build step, no framework. Fetches `data.json` client-side and renders
  it as a reading list ("Index") with a reading pane.

## Known limitations, read before relying on this

- **No "most viewed."** Substack doesn't expose view counts publicly —
  only likes (`reaction_count`), comments, and restacks. Engagement
  ranking uses those three; there's no way to get raw views from outside.
- **Undocumented API.** Every Substack field name here is inferred, not
  documented. If Substack changes their response shape, extraction may
  silently return 0s for engagement counts rather than erroring — call
  `SubstackClient.debug_dump_raw()`-style inspection (dump a raw
  `post.get_metadata()` dict to a file) if numbers look wrong, and check
  which keys are actually present.
- **`ddgs` rate limits.** The free web-search discovery path can get
  temporarily rate-limited under heavy use. It's built for occasional
  personal runs, not a crawler running every few minutes.
- **Copyright.** The synthesis prompt enforces paraphrase-plus-attribution
  and caps direct quotes, but review what it produces before publishing
  anything — a compiled article that leans too heavily on other people's
  paragraphs is a real legal exposure, not a hypothetical one, regardless
  of what the prompt asked for.
- **Reverse-engineered endpoints.** Substack's ToS isn't explicit about
  scraping their public JSON API; this operates on public, unauthenticated
  data at a conservative rate, which is a different risk profile than
  high-volume or commercial use. This isn't legal advice.

## Testing

```bash
pytest tests/ -v
```

Covers chunking, engagement scoring, field-mapping, and judge-response
parsing with mocked inputs — nothing here calls Substack, Groq, or Sheets
live, so it runs offline and free.
