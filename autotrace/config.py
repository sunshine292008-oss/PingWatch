from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    supabase_url: str = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    resend_api_key: str = os.getenv("RESEND_API_KEY", "")
    from_email: str = os.getenv("FROM_EMAIL", "alerts@autotrace.local")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    screenshot_dir: str = os.getenv("SCREENSHOT_DIR", "data/screenshots")
    screenshot_bucket: str = os.getenv("SCREENSHOT_BUCKET", "incident-screenshots")
    api_port: int = int(os.getenv("PORT", "8080"))
    crawl_max_pages: int = int(os.getenv("CRAWL_MAX_PAGES", "5"))
    request_timeout_ms: int = int(os.getenv("REQUEST_TIMEOUT_MS", "30000"))

    @property
    def supabase_configured(self) -> bool:
        return bool(
            self.supabase_url
            and self.supabase_service_key
            and self.supabase_url.startswith("http")
        )

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key.strip())


settings = Settings()