"""Config the nodes share."""

from functools import cache

import yaml

from app.settings import settings


@cache
def ownership() -> dict[str, dict]:
    return yaml.safe_load((settings.config_dir / "ownership.yaml").read_text())


def service_names() -> list[str]:
    return list(ownership())
