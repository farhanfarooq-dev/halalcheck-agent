"""Application configuration loaded from environment variables.

Real secrets belong in a local .env file. The committed .env.example file only
contains safe placeholders.
"""

from pathlib import Path
import os

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(dotenv_path: Path) -> bool:
        """Fallback for environments where python-dotenv is not installed yet."""
        return False


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/halalcheck.db")
APP_NAME = os.getenv("APP_NAME", "AI-HalalCheck-Agent")
APP_VERSION = os.getenv("APP_VERSION", "1.0")
APP_ACCESS_PASSWORD = os.getenv("APP_ACCESS_PASSWORD", "")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

OPENFOODFACTS_BASE_URL = os.getenv(
    "OPENFOODFACTS_BASE_URL",
    "https://world.openfoodfacts.org",
)

# Keep email safe by default. The email service should send only when this is
# explicitly changed to a sending mode in the local .env file.
EMAIL_MODE = os.getenv("EMAIL_MODE", "draft")
GMAIL_SENDER_EMAIL = os.getenv("GMAIL_SENDER_EMAIL", "halalcheckde@gmail.com")
GMAIL_CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "")
GMAIL_TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "")
SENDER_DISPLAY_NAME = os.getenv("SENDER_DISPLAY_NAME", "")
REPLY_TO_EMAIL = os.getenv("REPLY_TO_EMAIL", "")


def email_sending_enabled() -> bool:
    """Return True only when email sending is explicitly enabled."""
    return EMAIL_MODE.lower() == "send"
