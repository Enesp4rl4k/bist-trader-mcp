"""Keep every test away from the user's real journal, configs, alerts and caches."""

import pytest

_ENV_FILES = {
    "BIST_TRADE_JOURNAL": "journal.json",
    "BIST_RISK_CONFIG": "risk_config.json",
    "BIST_PA_WEIGHTS": "pa_weights.json",
    "BIST_ALERTS_FILE": "alerts.jsonl",
    "BIST_PANEL_DB": "panel.db",
    "BIST_FORECAST_DIR": "out",
}


@pytest.fixture(autouse=True)
def _isolated_user_files(tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("userfiles")
    for var, name in _ENV_FILES.items():
        monkeypatch.setenv(var, str(base / name))
    # Never talk to a real Telegram bot from tests.
    monkeypatch.delenv("BIST_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("BIST_TELEGRAM_CHAT_ID", raising=False)
