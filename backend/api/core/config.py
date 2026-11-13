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
