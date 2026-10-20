"""Start the weekday S:P9 collection at 10:50, deliver at 11:50."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any


LABEL = "com.sp9works.slashbot.daily-digest"
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DESTINATION = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
DATA_DIR = PROJECT_ROOT / ".sp9_data"


def build_plist(python: str | None = None) -> dict[str, Any]:
    python = python or sys.executable
    schedule = [
        {"Weekday": weekday, "Hour": hour, "Minute": minute}
        # launchd follows cron semantics: 0/7=Sunday, 1=Monday, ... 5=Friday.
        for weekday in range(1, 6)
        for hour, minute in ((10, 50), (11, 10), (11, 30))
    ]
    return {
        "Label": LABEL,
        "ProgramArguments": [
            python,
            str(PROJECT_ROOT / "sp9_digest.py"),
            "run",
            "--send-at",
            "11:50",
            "--skip-if-sent-today",
            "--attempts",
            "3",
            "--retry-delay-seconds",
            "120",
        ],
        "WorkingDirectory": str(PROJECT_ROOT),
        "StartCalendarInterval": schedule,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": str(DATA_DIR / "launchd.stdout.log"),
        "StandardErrorPath": str(DATA_DIR / "launchd.stderr.log"),
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "SP9_DIGEST_DATA_DIR": str(DATA_DIR),
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
    }


def write_plist(destination: Path = DEFAULT_DESTINATION, python: str | None = None) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        plistlib.dump(build_plist(python), handle, sort_keys=False)
    return destination


def _launchctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/launchctl", *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def install(destination: Path = DEFAULT_DESTINATION) -> None:
    path = write_plist(destination)
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(path), check=False)
    result = _launchctl("bootstrap", domain, str(path), check=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    print(f"Установлено: {path}")
    print(
        "Расписание: понедельник–пятница, основной запуск в 10:50, "
        "резервные в 11:10 и 11:30; отправка не раньше 11:50."
    )


def uninstall(destination: Path = DEFAULT_DESTINATION) -> None:
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(destination), check=False)
    if destination.exists():
        destination.unlink()
    print(f"Удалено: {destination}")


def status() -> int:
    result = _launchctl("print", f"gui/{os.getuid()}/{LABEL}", check=False)
    print(result.stdout.strip())
    return 0 if result.returncode == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Установка ежедневной сводки S:P9")
    parser.add_argument("command", choices=("install", "uninstall", "status", "print"))
    args = parser.parse_args()
    if args.command == "install":
        install()
    elif args.command == "uninstall":
        uninstall()
    elif args.command == "status":
        return status()
    else:
        plistlib.dump(build_plist(), sys.stdout.buffer, sort_keys=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
