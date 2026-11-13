import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Settings:
    frontend_origin: str = field(
        default_factory=lambda: os.getenv("FRONTEND_ORIGIN", "")
    )
    repo_backend: str = field(
        default_factory=lambda: os.getenv("REPO_BACKEND", "memory").lower()
    )
    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "")
    )
    exa_api_key: str = field(
        default_factory=lambda: os.getenv("EXA_API_KEY", "")
    )
    tinyfish_api_key: str = field(
        default_factory=lambda: os.getenv("TINYFISH_API_KEY", "")
    )
    supabase_url: str = field(
        default_factory=lambda: os.getenv("SUPABASE_URL", "")
    )
    supabase_service_key: str = field(
        default_factory=lambda: os.getenv("SUPABASE_SERVICE_KEY", "")
    )
    demo_mode: bool = field(
        default_factory=lambda: os.getenv("DEMO_MODE", "false").lower()
        in ("true", "1", "yes")
    )
    external_services_enabled: str = field(
        default_factory=lambda: os.getenv(
            "EXTERNAL_SERVICES_ENABLED", "gemini,exa,tinyfish,supabase"
        )
    )

    @property
    def cors_origins(self) -> List[str]:
        raw = self.frontend_origin.strip()
        if not raw:
            return []
        if raw == "*":
            return ["*"]
        origins = []
        for item in raw.split(","):
            cleaned = item.strip().rstrip("/")
            if cleaned:
                origins.append(cleaned)
        return origins

    @property
    def enabled_services(self) -> List[str]:
        if not self.external_services_enabled:
            return []
        return [
            s.strip().lower()
            for s in self.external_services_enabled.split(",")
            if s.strip()
        ]
