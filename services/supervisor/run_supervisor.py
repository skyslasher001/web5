"""Entry point used by Electron: `python -I -S services/supervisor/run_supervisor.py`.

-I ignores PYTHON* env vars and the user site; -S skips site-packages entirely. The supervisor
therefore runs on the standard library alone, so no dependency upgrade can break it (ADR-0001).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from universe_supervisor.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
