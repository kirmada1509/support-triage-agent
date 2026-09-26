"""The Alembic config, for running migrations from code (app.migrate, tests)."""

from alembic.config import Config

from app.settings import ROOT


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(toml_file=ROOT / "pyproject.toml")
    if url:
        cfg.attributes["url"] = url
    return cfg
