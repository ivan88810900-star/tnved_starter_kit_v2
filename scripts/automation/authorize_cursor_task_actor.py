#!/usr/bin/env python3
"""Check whether github.actor is allowed to run cursor-task automation."""

from __future__ import annotations

import os
import sys

DEFAULT_TRUSTED_ACTOR = "ivan88810900-star"


def trusted_actor_logins(extra: str) -> set[str]:
    actors = {DEFAULT_TRUSTED_ACTOR}
    for part in extra.split(","):
        login = part.strip()
        if login:
            actors.add(login)
    return actors


def is_authorized(actor: str, extra: str) -> bool:
    actor = actor.strip()
    if not actor:
        return False
    return actor in trusted_actor_logins(extra)


def main() -> int:
    actor = os.environ.get("GITHUB_ACTOR", "").strip()
    extra = os.environ.get("CURSOR_TASK_TRUSTED_ACTORS", "").strip()
    authorized = is_authorized(actor, extra)

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(f"authorized={'true' if authorized else 'false'}\n")

    if not authorized:
        print(
            f"::warning::Actor {actor!r} is not in cursor-task trusted allowlist.",
            file=sys.stderr,
        )
        return 0
    print(f"Authorized actor: {actor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
