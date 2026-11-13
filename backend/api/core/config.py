"""Validate per-tier deployment configuration without default credentials."""
from pathlib import Path
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Require an operator signing key and a separately selected database."""
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / '.env', extra='ignore')
    MONGODB_URI: str
    MONGODB_DB: str
    JWT_SECRET: SecretStr
    JWT_ISSUER: str = 'kp-etsip'
    JWT_EXPIRY_HOURS: int = 8
    CORS_ORIGINS: str = ''
    ENVIRONMENT: str = 'development'
    API_HOST: str = '0.0.0.0'
    API_PORT: int = 8000
    SEED_ON_STARTUP: bool = False
    SEED_ADMIN_PASSWORD: SecretStr | None = None
    SEED_DEMO_PASSWORD: SecretStr | None = None

    def require_seed_passwords(self) -> tuple[str, str]:
        """Require explicit non-sample credentials without exposing their values.

        Raises:
            ValueError: If either seed credential is absent, sample, or truncated by bcrypt.
        """
        values = []
        for key in ("SEED_ADMIN_PASSWORD", "SEED_DEMO_PASSWORD"):
            secret = getattr(self, key)
            raw = secret.get_secret_value() if secret else ""
            if not raw.strip() or "\0" in raw or len(raw.encode("utf-8")) > 72 or any(
                word in raw.lower() for word in ("dummy", "change-me", "change-in-production", "placeholder", "password", "example", "replace-me")
            ):
                raise ValueError(f"{key} requires an operator-supplied non-sample credential")
            values.append(raw)
        return values[0], values[1]
    @field_validator('JWT_SECRET')
    @classmethod
    def real_key(cls, value: SecretStr) -> SecretStr:
        """Reject sample and weak signing keys before accepting requests."""
        raw = value.get_secret_value()
        if len(raw) < 32 or any(word in raw.lower() for word in ('change-me', 'change-in-production', 'dummy', 'dev-secret')):
            raise ValueError('JWT_SECRET requires a generated deployment key')
        return value
    @field_validator('JWT_EXPIRY_HOURS')
    @classmethod
    def positive_expiry(cls, value: int) -> int:
        """Reject nonpositive token lifetimes."""
        if value <= 0:
            raise ValueError('JWT_EXPIRY_HOURS must be positive')
        return value
    @field_validator('MONGODB_URI', 'MONGODB_DB')
    @classmethod
    def nonempty(cls, value: str) -> str:
        """Reject absent database configuration."""
        if not value.strip():
            raise ValueError('Database configuration is required')
        return value
    @property
    def cors_origins(self) -> list[str]:
        """Split explicitly configured browser origins."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(',') if origin.strip()]
