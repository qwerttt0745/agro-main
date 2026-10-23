import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("AGRO_DATA_DIR",str(ROOT / "data")))
CHROMA_DIR = DATA / "chroma"
CHATS_DB = DATA / "chats.db"
PDF_DIR = DATA / "pdfs"

# Load local settings without replacing explicit environment variables.
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
