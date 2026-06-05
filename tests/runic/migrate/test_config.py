from pathlib import Path

from runic.migrate.config import Config


def test_config_defaults() -> None:
    cfg = Config(script_location=Path("runic"))
    assert cfg.script_location == Path("runic")
    assert cfg.version_strategy == "node"


def test_config_custom_strategy() -> None:
    cfg = Config(script_location=Path("migrations"), version_strategy="redis_key")
    assert cfg.version_strategy == "redis_key"
