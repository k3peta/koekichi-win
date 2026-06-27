from __future__ import annotations

import sys

from windows_voice_typer.cli import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["run"]))
