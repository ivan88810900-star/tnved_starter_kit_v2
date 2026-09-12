"""Optional native OpenAI Agents API adapter; Work remains the active backend.

No scheduler, shell executor, publication tool, or pretend subagent is implemented.
Set OPENAI_API_KEY in the application secret store and TARIFF_OPENAI_MODEL to an
available model. Never put keys in arguments, Git, prompts, or hosted env vars.
Hosted sessions receive no GitHub/production credentials and have network disabled.
This adapter does not turn a successful model response into QA or CI approval.

Official schemas checked 2026-09-12:
https://developers.openai.com/api/docs/guides/agents-api/multi-agent
https://developers.openai.com/api/docs/guides/agents-api/sessions
https://developers.openai.com/api/docs/guides/agents-api/sessions/events
https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted
https://developers.openai.com/api/docs/guides/agents-api/environments/files
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path


class RuntimeBlocked(RuntimeError):
    """Safe diagnostic: never contains a remote body, key, or input content."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeBlocked("API redirect refused")


def request_json(url, *, method, headers, payload=None, timeout=45):
    """Bounded HTTPS transport to fixed providers; no redirect or retry of writes."""
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc not in
            {"api.openai.com", "api.anthropic.com"} or parsed.fragment):
        raise RuntimeBlocked("API endpoint refused")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    if body is not None and len(body) > 2_000_000:
        raise RuntimeBlocked("API request exceeds byte limit")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise RuntimeBlocked("API response exceeds byte limit")
            if not raw:
                return {}
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise RuntimeBlocked("API response is not an object")
            return result
    except urllib.error.HTTPError as exc:
        # Do not include exception repr/reason/body, which may echo credentials.
        raise RuntimeBlocked(f"API request failed (HTTP {int(exc.code)})") from None
    except (urllib.error.URLError, OSError, ValueError):
        raise RuntimeBlocked("API transport or JSON response failed") from None


def preflight(environ=None):
    """Report configuration only; credentials present does not establish access."""
    env = os.environ if environ is None else environ
    def provider(names):
        missing = [name for name in names if not env.get(name, "").strip()]
        return {"status": "UNAVAILABLE" if missing else "CONFIGURED_UNVERIFIED",
                "missing": missing, "live_verified": False}
    return {
        "active_backend": "native_work",
        "native_work": "Requires the parent Work/Codex harness subagent tools",
        "agents_api": provider(("OPENAI_API_KEY", "TARIFF_OPENAI_MODEL")),
        "agents_api_scope": "SAFE_BOOTSTRAP_ONLY",
        "repository_integration_verified": False,
        "a6": provider(("ANTHROPIC_API_KEY", "TARIFF_ANTHROPIC_MODEL")),
        "max_concurrent_subagents": 3,
    }


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", value):
        raise RuntimeBlocked("Invalid API identifier")
    return value


def _summary(session):
    environment = session.get("environment") or {}
    actions = session.get("required_actions", [])
    if not isinstance(environment, dict) or not isinstance(actions, list):
        raise RuntimeBlocked("Invalid API session shape")
    action_types = set()
    for action in actions:
        if not isinstance(action, dict):
            raise RuntimeBlocked("Invalid API required action")
        kind = action.get("type")
        action_types.add(kind if kind in {"function_call", "environment_connection"} else "unknown")
    environment_id = environment.get("id")
    return {"id": _identifier(session.get("id")), "status": _status(session.get("status")),
            "environment_id": None if environment_id is None else _identifier(environment_id),
            "required_action_types": sorted(action_types),
            "backend": "openai_agents_api", "scope": "SAFE_BOOTSTRAP_ONLY",
            "repository_integration_verified": False}


def _status(value):
    allowed = {"pending", "created", "queued", "running", "in_progress", "idle",
               "requires_action", "failed", "cancelled", "completed"}
    return value if isinstance(value, str) and value in allowed else "unknown"


def _safe_text(value, env):
    from .audit import ensure_safe_text
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > 200_000:
        raise RuntimeBlocked("Text input is empty or exceeds byte limit")
    ensure_safe_text(value, environ=env)


class AgentsAPIClient:
    """A small REST adapter, not a replacement for the managed agent harness."""

    def __init__(self, environ=None):
        self._env = os.environ if environ is None else environ
        self._key = self._env.get("OPENAI_API_KEY", "").strip()
        if not self._key:
            raise RuntimeBlocked("OPENAI_API_KEY is unavailable; no API session started")

    def _request(self, path, *, payload=None):
        return request_json("https://api.openai.com/v1/agents/sessions" + path,
                            method="GET" if payload is None else "POST",
                            headers={"Authorization": "Bearer " + self._key,
                                     "OpenAI-Beta": "agents=v1",
                                     "Content-Type": "application/json"}, payload=payload)

    def create_session(self, instructions, input_text, files=None):
        """Start real managed multi-agent work. Files are explicit text inputs only.

        File inputs are not a full repository checkout. The native Work workflow
        owns Git isolation/publication. A0 must not claim this API smoke is a full
        repository integration run without separate worktree/QA/CI evidence.
        """
        from .audit import ensure_safe_path, ensure_safe_text
        model = self._env.get("TARIFF_OPENAI_MODEL", "").strip()
        if not model or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", model):
            raise RuntimeBlocked("Set TARIFF_OPENAI_MODEL to an available model")
        _safe_text(instructions, self._env)
        _safe_text(input_text, self._env)
        if files is not None and not isinstance(files, Mapping):
            raise RuntimeBlocked("Explicit text file mapping required")
        uploads = []
        total = 0
        for path, content in (files or {}).items():
            ensure_safe_path(path)
            ensure_safe_text(content, environ=self._env)
            raw = content.encode("utf-8")
            total += len(raw)
            if len(raw) > 200_000 or total > 500_000 or len(uploads) >= 50:
                raise RuntimeBlocked("Hosted file scope exceeds safe upload limit")
            uploads.append({"type": "inline", "path": "/workspace/" + path,
                            "data": base64.b64encode(raw).decode("ascii")})
        environment = {"type": "openai_hosted", "network": {"access": "disabled"}}
        if uploads:
            environment["files"] = uploads
        payload = {"agent": {"model": model, "instructions": instructions,
                             "multi_agent": {"enabled": True, "max_concurrent_subagents": 3}},
                   "environment": environment, "input": input_text, "stream": False}
        return _summary(self._request("", payload=payload))

    def retrieve_session(self, session_id):
        return _summary(self._request("/" + _identifier(session_id)))

    def resume_session(self, session_id, input_text):
        """Submit one follow-up; no automatic retry because delivery may have happened."""
        session_id = _identifier(session_id)
        _safe_text(input_text, self._env)
        previous = self.retrieve_session(session_id)
        if previous["status"] in {"failed", "cancelled", "unknown"} or previous["required_action_types"]:
            raise RuntimeBlocked("Session needs lifecycle recovery before new input")
        self._request("/" + session_id + "/events", payload={"events": [{
            "type": "agent.session.input.message", "input": [{"role": "user",
                "content": [{"type": "input_text", "text": input_text}]}]}]})
        return {"id": session_id, "status": "INPUT_SUBMITTED", "completed": False}

    def _pages(self, session_id, resource, max_pages):
        if type(max_pages) is not int or not 1 <= max_pages <= 20:
            raise RuntimeBlocked("History page limit must be between 1 and 20")
        rows, after, seen = [], None, set()
        for _ in range(max_pages):
            query = {"order": "asc", "limit": 100}
            if after:
                query["after"] = after
            page = self._request("/" + session_id + "/" + resource + "?" +
                                 urllib.parse.urlencode(query))
            data = page.get("data")
            if not isinstance(data, list) or len(data) > 100:
                raise RuntimeBlocked("Invalid history page")
            rows.extend(data)
            if page.get("has_more") is False:
                return rows
            if page.get("has_more") is not True:
                raise RuntimeBlocked("History completeness is unknown")
            after = _identifier(page.get("last_id"))
            if after in seen:
                raise RuntimeBlocked("History cursor repeated")
            seen.add(after)
        raise RuntimeBlocked("History is incomplete at the configured page limit")

    def history(self, session_id, max_pages=10):
        """Return content-free, complete-within-bounds session evidence.

        Session-wide agent IDs must not be presented as proof for a specific task.
        A0 binds task completion using its task ID, commit SHA and reviewed output.
        """
        session_id = _identifier(session_id)
        session = self.retrieve_session(session_id)
        items = self._pages(session_id, "items", max_pages)
        turns = self._pages(session_id, "turns", max_pages)
        clean = []
        for turn in turns:
            if not isinstance(turn, dict) or "subagent_id" not in turn:
                raise RuntimeBlocked("Turn attribution missing")
            sid = turn["subagent_id"]
            clean.append({"id": _identifier(turn.get("id")),
                          "subagent_id": None if sid is None else _identifier(sid),
                          "status": _status(turn.get("status"))})
        roots = [turn for turn in clean if turn["subagent_id"] is None]
        children = sorted({turn["subagent_id"] for turn in clean if turn["subagent_id"]})
        return {"session": session, "history_complete": True, "item_count": len(items),
                "turns": clean, "observed_subagent_ids": children,
                "latest_root_turn": roots[-1] if roots else None,
                "proof_scope": "session_history_only", "task_passed": False}


def extract_event_proof(events, *, root_turn_id):
    """Extract attribution facts from an authenticated stream slice for one turn.

    Caller must bind the stream to its session and preserve original evidence.
    This pure parser cannot authenticate supplied events (fixtures are not proof).
    It never infers subagents from role names or model-generated text.
    """
    root_turn_id = _identifier(root_turn_id)
    children, terminal, count = set(), None, 0
    for event in events:
        count += 1
        if count > 10_000:
            raise RuntimeBlocked("Event proof exceeds bound")
        if not isinstance(event, dict):
            raise RuntimeBlocked("Invalid event evidence")
        kind = event.get("type", "")
        turn = event.get("turn")
        if not kind.startswith("agent.session.turn.") or not isinstance(turn, dict):
            continue
        if "subagent_id" not in turn:
            continue  # Missing attribution is not evidence of a root turn.
        sid = turn["subagent_id"]
        if sid is not None:
            children.add(_identifier(sid))
        elif turn.get("id") == root_turn_id:
            if kind in {"agent.session.turn.completed", "agent.session.turn.failed",
                        "agent.session.turn.cancelled"}:
                outcome = kind.rsplit(".", 1)[-1]
                if terminal is not None and terminal != outcome:
                    raise RuntimeBlocked("Conflicting terminal evidence for one root turn")
                terminal = outcome
    return {"root_turn_id": root_turn_id, "root_outcome": terminal,
            "root_completed": terminal == "completed", "subagent_ids": sorted(children),
            "distinct_subagents": len(children), "event_count": count,
            "proof_scope": "unverified_stream_slice",
            "authenticated_by_parser": False, "task_passed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    create = commands.add_parser("create")
    create.add_argument("--instructions-file", required=True)
    create.add_argument("--input-file", required=True)
    for name in ("retrieve", "resume", "history"):
        command = commands.add_parser(name)
        command.add_argument("session_id")
        if name == "resume":
            command.add_argument("--input-file", required=True)
        if name == "history":
            command.add_argument("--max-pages", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight()
        else:
            client = AgentsAPIClient()
            if args.command == "create":
                result = client.create_session(Path(args.instructions_file).read_text(),
                                               Path(args.input_file).read_text())
            elif args.command == "resume":
                result = client.resume_session(args.session_id, Path(args.input_file).read_text())
            elif args.command == "history":
                result = client.history(args.session_id, args.max_pages)
            else:
                result = client.retrieve_session(args.session_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except RuntimeBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 2
    except (OSError, ValueError):
        print(json.dumps({"status": "BLOCKED", "reason": "Invalid or unreadable input"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
