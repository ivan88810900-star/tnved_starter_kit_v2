"""Run the pinned reference pilot on loopback with an optional local login profile."""
import argparse
import json
import os
from pathlib import Path
import stat
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18017)
    parser.add_argument("--auth-file", type=Path)
    parser.add_argument("--sgr-evidence", type=Path, help="Pinned local public registry excerpt for the authenticated pilot")
    args = parser.parse_args()
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
    os.execve(sys.executable, [
        sys.executable, "-B", "-m", "uvicorn", "app.local_pilot:create_app", "--factory",
        "--app-dir", str(BACKEND), "--host", "127.0.0.1", "--port", str(args.port),
        "--no-access-log",
    ], env)


if __name__ == "__main__":
    main()
