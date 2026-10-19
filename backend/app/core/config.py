"""
CipherQ Core Configuration Module
Loads application settings with Pydantic BaseSettings.
All sensitive file locations are kept configurable and outside source tracking.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent  # D:\Downloads\CipherQ

class Settings(BaseSettings):
    PROJECT_NAME: str = "CipherQ"
    VERSION: str = "1.0.0-rc1"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    MIN_FREE_DISK_BYTES: int = 1_000_000_000  # 1 GB host storage safety margin for OS, logs, SQLite WAL
    
    # Storage and Vault Paths
    DATA_DIR: Path = BASE_DIR / "data"
    VAULT_DIR: Path = BASE_DIR / "data" / "vault"
    KEYS_DIR: Path = BASE_DIR / "keys"
    MASTER_KEY_PATH: Path = BASE_DIR / "keys" / ".vault_master.key"
    
    # Database
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'cipherq.db'}"
    
    # Session & Security Settings
    SESSION_EXPIRE_HOURS: int = 24
    SESSION_COOKIE_NAME: str = "cipherq_session"
    COOKIE_SECURE: bool = False  # Set to True when TLS/HTTPS is active
    COOKIE_SAMESITE: str = "lax"
    CORS_ALLOWED_ORIGINS: str = "https://nimalan-parameswaran.github.io"
    
    # Rate Limiting (per IP address)
    AUTH_RATE_LIMIT_LOGIN_MAX: int = 5
    AUTH_RATE_LIMIT_LOGIN_WINDOW_SEC: int = 60
    AUTH_RATE_LIMIT_REGISTER_MAX: int = 3
    AUTH_RATE_LIMIT_REGISTER_WINDOW_SEC: int = 60
    
    # Plan Storage Caps (Decimal GB: 1 GB = 1,000,000,000 bytes)
    FREE_QUOTA_BYTES: int = 1_000_000_000       # 1 GB
    PREMIUM_QUOTA_BYTES: int = 5_000_000_000    # 5 GB
    CREATOR_QUOTA_BYTES: int = 25_000_000_000   # 25 GB
    PRIVATE_VAULT_QUOTA_BYTES: int = 5_000_000_000
    VAULT_AI_QUOTA_BYTES: int = 5_000_000_000

    # Administrative Operations Token (Development / Local Administration)
    ADMIN_TOKEN: str = "cipherq-dev-admin-secret-2026"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def init_directories(self) -> None:
        """Ensure necessary local storage directories exist."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.VAULT_DIR.mkdir(parents=True, exist_ok=True)
        self.KEYS_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
