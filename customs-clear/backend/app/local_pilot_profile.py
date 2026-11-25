"""Run the pinned reference pilot on loopback with an optional local login profile."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat
from contextlib import closing
import sys

BACKEND = Path(__file__).resolve().parents[1]
AUTH_FIELDS = {"SECRET_KEY", "ADMIN_PASSWORD", "VIEWER_PASSWORD", "DECLARANT_PASSWORD"}
PATH_FIELDS = {
    "catalog_and_rates": "TARIFF_PILOT_DATA",
    "additional_rates": "TARIFF_PILOT_ADDITIONAL_RATES",
    "partitioned_rates": "TARIFF_PILOT_PARTITIONED_RATES",
    "frontend": "TNVED_RECOVERY_FRONTEND",
}


def read_auth_file(path: Path) -> dict[str, str]:
    # Only a separately provisioned local file can enable login.
    parent = path.parent.resolve(strict=True)
    if any((p / ".git").exists() for p in (parent, *parent.parents)):
        raise ValueError("The authentication file must be outside Git")
    fd = os.open(parent / path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 16384):
            raise ValueError("Expected an owner-only regular authentication file (0600)")
        values = json.load(stream)
    if not isinstance(values, dict) or set(values) != AUTH_FIELDS:
        raise ValueError("Incorrect authentication field set")
    if not all(isinstance(v, str) and v.strip() and v == v.strip() for v in values.values()):
        raise ValueError("Incomplete authentication profile")
    if len(values["SECRET_KEY"].encode()) < 32:
        raise ValueError("HS256 requires a signing key of at least 32 bytes")
    return values


def restore_local_drafts(previous: Path, current: Path) -> None:
    """Carry a stopped pilot's draft rows into its replacement before serving HTTP."""
    parent = previous.parent
    if (previous.name != "invoice-drafts.sqlite" or not parent.name.startswith("tariff-invoice-handoff-")
            or parent.is_symlink() or previous.is_symlink() or not previous.is_file()
            or parent.stat().st_uid != os.getuid() or stat.S_IMODE(parent.stat().st_mode) != 0o700
            or previous.stat().st_uid != os.getuid() or previous.samefile(current)):
        raise ValueError("Expected the private handoff of a stopped local pilot")
    # An immutable SQLite reader would ignore unapplied journal contents.
    if any(Path(str(previous) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Draft handoff contains an outstanding SQLite journal")
    with previous.open("rb") as source:
        # Header bytes 18 and 19 are SQLite's write/read format versions.
        source.seek(18)
        if source.read(2) != bytes((1, 1)):
            raise ValueError("Draft handoff requires the pilot rollback-journal mode")
    base = ("owner", "draft_id", "line", "description", "quantity", "unit", "selected_code")
    with closing(sqlite3.connect(previous.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as src, closing(sqlite3.connect(current)) as dst:
        src.execute("PRAGMA trusted_schema=OFF")
        if src.execute("SELECT type FROM sqlite_schema WHERE name='draft_lines'").fetchall() != [("table",)]:
            raise ValueError("Unexpected draft table")
        columns = tuple(r[1] for r in src.execute("PRAGMA table_info(draft_lines)"))
        if columns not in (base, (*base, "clarification")) or src.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError("Unrecognized or damaged local drafts")
        if dst.execute("SELECT 1 FROM draft_lines LIMIT 1").fetchone():
            raise ValueError("Fresh pilot drafts expected")
        fields = ",".join(columns)
        with dst:
            dst.executemany(f"INSERT INTO draft_lines ({fields}) VALUES ({','.join('?' for _ in columns)})",
                            src.execute(f"SELECT {fields} FROM draft_lines"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18017)
    parser.add_argument("--auth-file", type=Path)
    parser.add_argument("--sgr-evidence", type=Path, help="Pinned local public registry excerpt for the authenticated pilot")
    parser.add_argument("--resume-local-drafts", type=Path, help="Private temporary handoff during an authenticated pilot update")
    args = parser.parse_args()
    if args.resume_local_drafts and not args.auth_file:
        parser.error("draft handoff requires the authenticated local profile")
    if args.sgr_evidence and not args.auth_file:
        parser.error("the optional local registry excerpt requires the authenticated profile")
    if not 1 <= args.port <= 65535:
        parser.error("invalid loopback port")
    config = json.loads(args.config.read_text())
    if set(config) != set(PATH_FIELDS) | {"partitioned_chapters"}:
        parser.error("unexpected pilot configuration")
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONNOUSERSITE": "1",
    }
    if os.environ.get("PYTHONPATH"):
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    for field, variable in PATH_FIELDS.items():
        path = (args.root / config[field]).resolve(strict=True)
        if not path.is_dir():
            parser.error(f"expected a directory for {field}")
        env[variable] = str(path)
    if not (Path(env["TNVED_RECOVERY_FRONTEND"]) / "index.html").is_file():
        parser.error("build the local pilot frontend first")
    env["TARIFF_PILOT_PARTITIONED_CHAPTERS"] = ",".join(config["partitioned_chapters"])
    if args.auth_file is not None:
        try:
            env.update(read_auth_file(args.auth_file))
        except (OSError, ValueError):
            parser.error("cannot load the private local authentication file")
        env.update(TARIFF_PILOT_LOGIN="1", AUTH_ACCESS_COOKIE_NAME="tariff_pilot_session",
                   AUTH_ACCESS_COOKIE_PATH="/api", AUTH_ACCESS_COOKIE_SAMESITE="strict")
    if args.sgr_evidence:
        path = args.sgr_evidence.resolve(strict=True)
        if not path.is_file():
            parser.error("expected a local registry evidence file")
        env["TARIFF_PILOT_SGR_EVIDENCE"] = str(path)
    if args.resume_local_drafts:
        env["TARIFF_PILOT_RESUME_DRAFTS"] = str(args.resume_local_drafts.absolute())
    os.execve(sys.executable, [
        sys.executable, "-B", "-m", "uvicorn", "app.local_pilot:create_app", "--factory",
        "--app-dir", str(BACKEND), "--host", "127.0.0.1", "--port", str(args.port),
        "--no-access-log",
    ], env)


if __name__ == "__main__":
    main()
