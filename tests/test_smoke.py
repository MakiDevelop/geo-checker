"""Smoke tests for project skeleton."""


def test_cli_importable() -> None:
    from src.cli.run import app

    assert app is not None
