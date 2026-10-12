"""Run Core: `python -m universe_core` (normally started by the supervisor)."""

import sys

import uvicorn

from universe_common.log import configure_logging, register_secret
from universe_core.app import create_app
from universe_core.settings import CoreSettings, SettingsError


def main() -> int:
    try:
        settings = CoreSettings.from_env()
    except SettingsError as exc:
        print(f"universe-core: {exc}", file=sys.stderr)
        return 2
    configure_logging("core", settings.log_dir, console=settings.log_console)
    register_secret(settings.session_token)
    uvicorn.run(
        create_app(settings),
        host="127.0.0.1",
        port=settings.port,
        log_config=None,
        access_log=False,
        lifespan="on",
        timeout_graceful_shutdown=3,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
