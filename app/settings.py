from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent

# Model providers (Pydantic AI, LiteLLM) read their API keys from the environment.
load_dotenv(ROOT / ".env.agent")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env.agent", extra="ignore")

    database_url: str = "postgresql://triage:triage@localhost:5433/triage"
    pylon_webhook_secret: str = "dev-secret"
    api_base_url: str = "http://localhost:8000"
    role_profile: str | None = None  # ROLE_PROFILE: a profile in config/roles.yaml
    role_models: str | None = None  # ROLE_MODELS: "role=model,..." overrides single roles
    config_dir: Path = ROOT / "config"

    @property
    def sqlalchemy_url(self) -> str:
        """DATABASE_URL for SQLAlchemy: same database, psycopg 3 driver (async capable)."""
        return (
            make_url(self.database_url)
            .set(drivername="postgresql+psycopg")
            .render_as_string(hide_password=False)
        )


settings = Settings()
