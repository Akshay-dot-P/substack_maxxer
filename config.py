"""
Central config. Everything tunable lives here so pipeline.py stays readable.
Reads from environment variables (via .env if python-dotenv is installed)
with sane defaults for a personal/portfolio-scale run.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional; env vars can be set directly

# --- LLM (Groq) -------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# llama-3.3-70b-versatile is the recommended default: strong enough for
# judging/synthesis, still fast and cheap on Groq. Swap to a smaller model
# (e.g. llama-3.1-8b-instant) for cheaper/faster dev-loop iteration.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# --- Embeddings ---------------------------------------------------------
# Matches your existing Pivot Resume Tool stack. all-MiniLM-L6-v2 is fast
# and good enough for this; swap to BAAI/bge-m3 if you want higher recall
# at the cost of a slower/heavier model.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# --- Discovery ------------------------------------------------------
DISCOVERY_WEB_RESULTS = int(os.getenv("DISCOVERY_WEB_RESULTS", "25"))
# publication_discovery does one full HTTP fetch per post (no cheap
# pre-filter available -- see discovery.py docstring), so keep these
# modest: 5 x 5 = 25 fetches at ~1-2s each is already ~30-50s.
DISCOVERY_PUBS_TO_CHECK = int(os.getenv("DISCOVERY_PUBS_TO_CHECK", "5"))
DISCOVERY_POSTS_PER_PUB = int(os.getenv("DISCOVERY_POSTS_PER_PUB", "5"))

# --- Ranking ----------------------------------------------------------
TOP_ARTICLES = int(os.getenv("TOP_ARTICLES", "8"))          # articles kept after engagement ranking
PASSAGES_PER_ARTICLE = int(os.getenv("PASSAGES_PER_ARTICLE", "3"))  # top chunks kept per article pre-judge
FINAL_PASSAGES = int(os.getenv("FINAL_PASSAGES", "10"))      # passages fed into synthesis

# Engagement weighting: restacks are the strongest signal (someone chose to
# re-share it to their own audience), comments next, plain likes weakest.
ENGAGEMENT_WEIGHTS = {"likes": 1.0, "comments": 2.0, "restacks": 3.0}

# --- HTTP behaviour toward Substack --------------------------------------
# Substack's endpoints are undocumented and will rate-limit/block aggressive
# clients. Keep this conservative for a personal-scale tool.
REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "1.2"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "15"))
USER_AGENT = (
    "Mozilla/5.0 (compatible; substack-synth/0.1; "
    "personal research tool; +https://github.com/)"
)

# --- Google Sheets (this is the "database") -----------------------------
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")  # the long ID in the sheet's URL

# --- Output (static site, for GitHub Pages) ------------------------------
# The pipeline writes JSON straight into this folder. Point GitHub Pages at
# this folder (Settings -> Pages -> Deploy from branch -> /docs) and it's
# a live site with no build step, no server, no hosting cost.
SITE_DIR = os.getenv("SITE_DIR", "./docs")
SITE_DATA_FILE = os.getenv("SITE_DATA_FILE", "data.json")
