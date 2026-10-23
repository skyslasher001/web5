"""Run argv[1:] as a child and wait for it, like the python.exe launcher in a Windows venv.

Supervisor tests use it to check that stopping or killing a service takes the real process too.
"""

import subprocess
import sys

if __name__ == "__main__":
    sys.exit(subprocess.call(sys.argv[1:]))
