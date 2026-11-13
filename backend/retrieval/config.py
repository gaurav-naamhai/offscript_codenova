"""Environment configuration, constants, and shared Supabase/Gemini clients."""

import os
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from google import genai

load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").strip()
# Support both SUPABASE_KEY (local .env) and SUPABASE_SERVICE_KEY (Gaurav's backend config)
SUPABASE_KEY: str = (
    os.getenv("SUPABASE_KEY", "").strip()
    or os.getenv("SUPABASE_SERVICE_KEY", "").strip()
)
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
TINYFISH_API_KEY: str = os.getenv("TINYFISH_API_KEY", "").strip()
EXA_API_KEY: str = os.getenv("EXA_API_KEY", "").strip()

EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001").strip()
EMBEDDING_DIM: int = 768
_raw_gemini_model = os.getenv("GEMINI_MODEL", "").strip()
GEMINI_MODEL: str = (
    "gemini-2.5-flash"
    if not _raw_gemini_model or _raw_gemini_model in ("gemini-3.5-flash-lite", "gemini-3.5-flash", "3.5-flash-lite")
    else _raw_gemini_model
)

TINYSEARCH_URL: str = "https://api.search.tinyfish.ai"
TINYFETCH_URL: str = "https://api.fetch.tinyfish.ai"
EXA_SEARCH_URL: str = "https://api.exa.ai/search"

_supabase_client: Optional[Client] = None
_genai_client: Optional[genai.Client] = None


def get_supabase_client() -> Client:
    """Return a singleton Supabase client initialized with service role credentials."""
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "Missing SUPABASE_URL or SUPABASE_KEY (or SUPABASE_SERVICE_KEY) in environment."
            )
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


def get_genai_client() -> genai.Client:
    """Return a singleton Google GenAI client."""
    global _genai_client
    if _genai_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("Missing GEMINI_API_KEY in environment.")
        _genai_client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options={"api_version": "v1beta"},
        )
    return _genai_client
