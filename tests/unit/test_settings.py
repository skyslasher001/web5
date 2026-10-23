import pytest

from universe_core.settings import CoreSettings, SettingsError

TOKEN = "x" * 40


def test_minimal_environment() -> None:
    s = CoreSettings.from_env({"UNIVERSE_SESSION_TOKEN": TOKEN, "UNIVERSE_DATA_DIR": "/d", "UNIVERSE_VAULT_DIR": "/v"})
    assert s.port == 47821
    assert s.allowed_origins == ("app://universe",)
    assert str(s.index_dir).replace("\\", "/") == "/v/.universe"
    assert not s.safe_mode


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "UNIVERSE_SESSION_TOKEN"),
        ({"UNIVERSE_SESSION_TOKEN": "short"}, "UNIVERSE_SESSION_TOKEN"),
        ({"UNIVERSE_SESSION_TOKEN": TOKEN, "UNIVERSE_CORE_PORT": "80"}, "between"),
        ({"UNIVERSE_SESSION_TOKEN": TOKEN, "UNIVERSE_OLLAMA_URL": "http://10.0.0.5:11434"}, "loopback"),
    ],
)
def test_invalid_environment(env: dict[str, str], message: str) -> None:
    with pytest.raises(SettingsError, match=message):
        CoreSettings.from_env(env)


def test_supervisor_restart_info_is_read() -> None:
    s = CoreSettings.from_env(
        {
            "UNIVERSE_SESSION_TOKEN": TOKEN,
            "UNIVERSE_START_REASON": "crash",
            "UNIVERSE_RESTART_COUNT": "3",
            "UNIVERSE_LAST_EXIT": "-9",
            "UNIVERSE_SAFE_MODE": "1",
            "UNIVERSE_ALLOWED_ORIGINS": "app://universe, http://127.0.0.1:5173",
        }
    )
    assert (s.start_reason, s.restart_count, s.last_exit, s.safe_mode) == ("crash", 3, "-9", True)
    assert s.allowed_origins == ("app://universe", "http://127.0.0.1:5173")
