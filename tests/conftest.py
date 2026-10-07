"""Shared harness: a throwaway config directory and a runner for the CLI."""

import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
import yaml

from trackthenews import core

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG_FILES = ("config.yaml", "rssfeeds.json", "matchlist.txt", "matchlist_case_sensitive.txt")


@pytest.fixture
def ttn(tmp_path, monkeypatch, capsys):
    """Copy the fixture config into tmp_path and return a runner for main().

    `run(*flags, **config)` merges `config` into config.yaml, runs the CLI, and
    returns ({url: (tweeted, tooted)}, stderr).
    """
    for name in CONFIG_FILES:
        shutil.copy(FIXTURES / name, tmp_path)
    monkeypatch.setattr(core.time, "sleep", lambda seconds: None)
    # main() rebinds module globals and logger handlers; restore them afterwards.
    monkeypatch.setattr(core, "config", {}, raising=False)
    monkeypatch.setattr(core.logger, "handlers", [])

    def run(*flags, **config):
        if config:
            path = tmp_path / "config.yaml"
            path.write_text(yaml.safe_dump(yaml.safe_load(path.read_text()) | config))
        monkeypatch.setattr(sys, "argv", ["trackthenews", *flags, str(tmp_path)])
        core.main()
        with closing(sqlite3.connect(tmp_path / "trackthenews.db")) as db:
            rows = db.execute("SELECT url, tweeted, tooted FROM articles").fetchall()
        return {url: (bool(t), bool(m)) for url, t, m in rows}, capsys.readouterr().err

    run.dir = tmp_path
    return run
