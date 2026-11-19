"""
Central configuration.

Every setting is read from environment variables (loaded from .env), so no
secret is ever hard-coded in the source and the same code runs on any machine.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = the folder that contains app.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/helpdesk"
)

DATA_DIR = PROJECT_ROOT / "data"
CHROMA_DIR = str(PROJECT_ROOT / "chroma_db")
CHROMA_COLLECTION = "helpdesk_policies"

# Company e-mail domain: addresses on this domain are not treated as PII.
COMPANY_EMAIL_DOMAIN = "goaified.example"

# How many document chunks the retriever returns per question
RETRIEVER_K = int(os.getenv("RETRIEVER_K", "4"))
