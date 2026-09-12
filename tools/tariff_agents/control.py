"""Deterministic A0 state, ownership and Git isolation. No provider/network calls.

Only TASK_BOARD.json is authoritative. The other JSON files are replaceable
projections. The Git common directory carries a process lock and local pointer
so sibling worktrees never become competing state writers. On a fresh clone the
tracked board is sufficient; stale worktree/session records are reported, never
silently relaunched. Worktrees are Git isolation, not a security sandbox.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import uuid

REPOSITORY = "ivan88810900-star/tnved_starter_kit_v2"
STATE_FILES = {".ai/TASK_BOARD.json", ".ai/AGENT_OWNERSHIP.json", ".ai/FINDINGS.json", ".ai/RUN_HISTORY.json"}
PROTECTED_BRANCHES = {"main", "master", "production", "prod", "feat/canonical-read-path", "feat/ntm-official-full-contours"}
STATUSES = {"NEW", "ALLOCATING", "ALLOCATED", "IN_PROGRESS", "IMPLEMENTED", "QA_PASSED", "AUDIT_PASSED", "CI_PENDING", "READY_FOR_HUMAN_APPROVAL", "CHANGES_REQUESTED", "CANCELLED", "INTEGRATED"}
ROLES = {"A1", "A2", "A3", "A4", "A5", "A6"}
PREFIX = {"A1": "rates", "A2": "ntm", "A3": "sources", "A4": "classification", "A5": "qa"}
SHA = re.compile(r"[0-9a-f]{40}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
SESSION_ID = re.compile(r"[A-Za-z0-9_./:-]{1,240}\Z")


class PolicyError(RuntimeError):
    """Constant diagnostics deliberately exclude command output and secrets."""


def need(condition, code):
    if not condition:
        raise PolicyError(code)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def safe_path(value):
    need(isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_./-]+", value)), "unsafe_path")
    parts = value.split("/")
    need(not value.startswith("/") and all(p not in {"", ".", "..", ".git"} for p in parts), "unsafe_path")
    need(not any(p.lower().startswith(".env") for p in parts), "sensitive_path")
    need(not any(re.search(r"(^|[_-])(secrets?|credentials?|passwords?|tokens?)([_.-]|$)", p, re.I) for p in parts), "sensitive_path")
    need(PurePosixPath(value).suffix.lower() not in {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12"}, "sensitive_path")
    return value


def safe_branch(value):
    need(isinstance(value, str) and value not in PROTECTED_BRANCHES, "protected_branch")
    need(bool(re.fullmatch(r"agent/[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value)), "unsafe_agent_branch")
    return value


def no_symlinks(path):
    path = Path(path).absolute()
    need(not any(p.is_symlink() for p in (path, *path.parents)), "symlink_forbidden")
    return path


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0"})
    result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-C", str(root), *args], env=env, capture_output=True, text=True, timeout=60)
    need(result.returncode == 0, "git_command_failed")
    return result.stdout.strip() if "-z" not in args else result.stdout


def _json_read(path):
    path = no_symlinks(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, encoding="utf-8") as source:
        content = source.read(8_000_001)
    need(len(content) <= 8_000_000, "state_too_large")
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        raise PolicyError("invalid_json_state") from None


def _atomic(path, value):
    path = no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tariff-state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, ensure_ascii=False, indent=2, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        no_symlinks(path)
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _nonoverlap(files):
    ordered = sorted(files)
    need(len(ordered) == len(set(ordered)), "duplicate_file")
    for index, name in enumerate(ordered):
        safe_path(name)
        need(not any(x.startswith(name + "/") for x in ordered[index + 1:]), "overlapping_file_scope")


def _tests(value):
    need(isinstance(value, list) and bool(value), "tests_required")
    for row in value:
        need(isinstance(row, dict) and isinstance(row.get("command"), str) and row["command"].strip(), "invalid_test_evidence")
        need(type(row.get("exit_code")) is int and row["exit_code"] == 0, "test_failed")
        need(isinstance(row.get("output"), str) and row["output"].strip(), "test_output_required")
    return deepcopy(value)


def _task(board, task_id):
    found = [t for t in board["tasks"] if t["id"] == task_id]
    need(len(found) == 1, "task_not_found")
    return found[0]


def validate_board(board):
    need(isinstance(board, dict) and board.get("schema_version") == 1, "unsupported_board_schema")
    need(board.get("max_concurrent_subagents") == 3 and type(board.get("revision")) is int, "invalid_board_config")
    need(all(isinstance(board.get(k), list) for k in ("tasks", "findings", "runs")), "invalid_board_collections")
    ids = set()
    scopes = []
    for task in board["tasks"]:
        need(isinstance(task, dict) and ID.fullmatch(task.get("id", "")), "invalid_task_id")
        need(task["id"] not in ids, "duplicate_task")
        ids.add(task["id"])
        need(task.get("owner") in PREFIX and task.get("status") in STATUSES, "invalid_task_state")
        need(task.get("risk") in {"low", "medium", "high", "critical"}, "invalid_risk")
        need(isinstance(task.get("files"), list) and task["files"], "files_required")
        _nonoverlap(task["files"])
        need(isinstance(task.get("dependencies"), list) and len(set(task["dependencies"])) == len(task["dependencies"]), "invalid_dependencies")
        need(isinstance(task.get("required_checks"), list) and all(isinstance(x, str) and x for x in task["required_checks"]) and len(set(task["required_checks"])) == len(task["required_checks"]), "invalid_required_checks")
        need(all(k in task for k in ("branch", "worktree", "tests", "qa", "external_audit", "refs", "author_sessions")), "incomplete_task")
        if task["branch"]:
            safe_branch(task["branch"])
        if task["status"] not in {"NEW", "CANCELLED", "INTEGRATED"} and task["branch"]:
            scopes.extend(task["files"])
    _nonoverlap(scopes)
    graph = {t["id"]: t["dependencies"] for t in board["tasks"]}
    visiting, visited = set(), set()
    def visit(node):
        need(node in graph, "unknown_dependency")
        need(node not in visiting, "dependency_cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)
    for node in graph:
        visit(node)
    active = [r for r in board["runs"] if r.get("status") == "RUNNING"]
    need(len(active) <= 3, "concurrency_limit")
    identities = [r.get("run_id", str(r.get("session_id")) + ":" + str(r.get("task_id"))) for r in board["runs"]]
    need(len(set(identities)) == len(identities), "duplicate_run")
    need(len({r.get("session_id") for r in active}) == len(active), "session_already_running")
    need(len({r.get("task_id") for r in active}) == len(active), "task_already_running")
    for run in board["runs"]:
        need(run.get("task_id") in ids and run.get("role") in ROLES and SESSION_ID.fullmatch(run.get("session_id", "")), "invalid_run")
    for task in board["tasks"]:
        if task["status"] in {"READY_FOR_HUMAN_APPROVAL", "INTEGRATED"}:
            _ready_evidence(task, board)
    return board


def _audit_passed(task, head, value):
    need(isinstance(value, dict), "bound_audit_result_required")
    need(value.get("head_sha") == head and value.get("base_sha") == task["refs"]["base_sha"], "audit_commit_mismatch")
    need(value.get("auditor") == "A6" and value.get("live_verified") is True and value.get("advisory_only") is True, "live_external_audit_required")
    need(isinstance(value.get("packet_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", value["packet_sha256"]), "audit_packet_hash_required")
    need(isinstance(value.get("model"), str) and value["model"] and isinstance(value.get("message_id"), str) and value["message_id"].startswith("msg_"), "audit_provider_receipt_required")
    need(value.get("a0_validated") is True and type(value.get("unresolved_findings")) is int and value["unresolved_findings"] == 0, "a0_audit_validation_required")
    findings = value.get("findings")
    need(isinstance(findings, list), "audit_findings_required")
    validations = value.get("finding_validations", [])
    need(isinstance(validations, list), "audit_validation_evidence_required")
    for finding in findings:
        need(isinstance(finding, dict) and isinstance(finding.get("id"), str), "invalid_audit_finding")
        matches = [v for v in validations if isinstance(v, dict) and v.get("id") == finding["id"]]
        need(len(matches) == 1 and matches[0].get("status") == "REJECTED" and isinstance(matches[0].get("evidence"), str) and matches[0]["evidence"].strip(), "audit_finding_not_adjudicated")


def _audit_unavailable(task, head, value):
    """Distinguish an optional provider not configured from a configured failure."""
    if isinstance(value, str):
        need(value.strip(), "audit_evidence_required")
        return "UNKNOWN"
    need(isinstance(value, dict) and value.get("status") == "UNAVAILABLE", "unavailable_receipt_required")
    need(value.get("head_sha") == head and value.get("base_sha") == task["refs"]["base_sha"], "audit_commit_mismatch")
    need(value.get("auditor") == "A6" and value.get("live_verified") is False and value.get("advisory_only") is True, "unavailable_audit_binding_required")
    need(isinstance(value.get("packet_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", value["packet_sha256"]), "audit_packet_hash_required")
    if "missing" in value:
        allowed_keys = {"auditor", "base_sha", "head_sha", "packet_sha256", "advisory_only", "a0_validation", "status", "missing", "live_verified"}
        need(set(value) == allowed_keys and value["a0_validation"] == "PENDING", "invalid_missing_configuration_receipt")
        missing = value["missing"]
        need(isinstance(missing, list) and missing and all(isinstance(x, str) for x in missing) and len(set(missing)) == len(missing), "invalid_missing_configuration")
        need(set(missing) <= {"ANTHROPIC_API_KEY", "TARIFF_ANTHROPIC_MODEL"}, "invalid_missing_configuration")
        return "NOT_CONFIGURED"
    need(isinstance(value.get("reason"), str) and value["reason"].strip(), "unavailable_reason_required")
    return "FAILED"


def _ready_evidence(task, board):
    head = task["refs"].get("head_sha")
    need(isinstance(head, str) and SHA.fullmatch(head), "readiness_head_missing")
    need(task["branch"] and isinstance(task["worktree"], str) and Path(task["worktree"]).is_absolute(), "ready_worktree_required")
    need(isinstance(task["refs"].get("base_sha"), str) and SHA.fullmatch(task["refs"]["base_sha"]), "full_base_sha_required")
    need(task["author_sessions"] and all(any(r["session_id"] == session and r["task_id"] == task["id"] and r["role"] == task["owner"] for r in board["runs"]) for session in task["author_sessions"]), "real_author_session_required")
    tests, qa, audit, ci = (task.get(k) for k in ("tests", "qa", "external_audit", "ci"))
    need(all(isinstance(x, dict) and x.get("head_sha") == head for x in (tests, qa, audit, ci)), "readiness_evidence_missing_or_stale")
    _tests(tests.get("commands"))
    _tests(qa.get("commands"))
    need(qa.get("status") == "PASSED" and qa.get("reviewer_session_id") not in task["author_sessions"], "independent_qa_required")
    need(any(r["session_id"] == qa["reviewer_session_id"] and r["task_id"] == task["id"] and r["role"] == "A5" and r.get("head_sha") == head for r in board["runs"]), "independent_qa_session_required")
    need(audit.get("reviewer") == "A6", "external_auditor_required")
    if audit.get("status") == "PASSED":
        _audit_passed(task, head, audit.get("evidence_ref"))
    elif audit.get("status") == "UNAVAILABLE":
        availability = _audit_unavailable(task, head, audit.get("evidence_ref"))
        need(task["risk"] in {"low", "medium"} or availability == "NOT_CONFIGURED", "high_risk_audit_required")
    else:
        need(task["risk"] in {"low", "medium"} and audit.get("status") == "NOT_REQUIRED", "high_risk_audit_required")
        need(isinstance(audit.get("evidence_ref"), str) and audit["evidence_ref"].strip(), "audit_evidence_required")
    checks = ci.get("checks")
    need(ci.get("status") == "PASSED" and isinstance(checks, list) and checks and task["required_checks"], "required_ci_checks_missing")
    names = set()
    for check in checks:
        need(isinstance(check, dict) and check.get("head_sha") == head and check.get("conclusion") == "success", "readiness_ci_invalid")
        need(isinstance(check.get("name"), str) and check["name"] not in names, "duplicate_ci_check")
        names.add(check["name"])
        need(type(check.get("run_id")) is int and check["run_id"] > 0 and check.get("url") == f"https://github.com/{REPOSITORY}/actions/runs/{check['run_id']}", "ci_provenance_required")
    need(set(task["required_checks"]) <= names, "required_ci_checks_missing")
    need(not any(f["task_id"] == task["id"] and f["status"] in {"UNVALIDATED", "CONFIRMED"} for f in board["findings"]), "unresolved_findings")


class StateStore:
    def __init__(self, root):
        root = no_symlinks(root)
        self.root = Path(git(root, "rev-parse", "--show-toplevel"))
        need(self.root == root, "repository_root_required")
        self.common = no_symlinks(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        self.control = self.common / "tariff-agents"

    @contextmanager
    def lock(self):
        """Nonblocking cross-process, cross-worktree A0 lock; never steal leases."""
        no_symlinks(self.control)
        self.control.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(no_symlinks(self.control / "a0.lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PolicyError("a0_lock_busy") from None
            yield
        finally:
            os.close(fd)

    def _root(self):
        pointer = self.control / "authority.json"
        if not pointer.exists():
            return self.root
        path = no_symlinks(_json_read(pointer)["root"])
        need(path.is_dir(), "state_authority_missing")
        need(Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")) == self.common, "state_authority_repository_mismatch")
        return path

    def _load(self):
        return validate_board(_json_read(self._root() / ".ai/TASK_BOARD.json"))

    def _project(self, board):
        root = self._root()
        ownership = {name: {"task_id": t["id"], "owner": t["owner"], "branch": t["branch"], "worktree": t["worktree"]} for t in board["tasks"] if t["branch"] and t["status"] not in {"NEW", "CANCELLED", "INTEGRATED"} for name in t["files"]}
        for filename, key, value in (("AGENT_OWNERSHIP.json", "files", ownership), ("FINDINGS.json", "findings", board["findings"]), ("RUN_HISTORY.json", "runs", board["runs"])):
            _atomic(root / ".ai" / filename, {"schema_version": 1, "board_revision": board["revision"], key: value})

    def _save(self, board):
        validate_board(board)
        board["revision"] += 1
        board["updated_at"] = utcnow()
        _atomic(self._root() / ".ai/TASK_BOARD.json", board)
        self._project(board)

    def initialize(self):
        with self.lock():
            root = self._root()
            if (root / ".ai/TASK_BOARD.json").exists():
                board = self._load()
            else:
                board = {"schema_version": 1, "revision": 0, "max_concurrent_subagents": 3, "tasks": [], "findings": [], "runs": [], "updated_at": utcnow()}
                _atomic(root / ".ai/TASK_BOARD.json", board)
            if not (self.control / "authority.json").exists():
                _atomic(self.control / "authority.json", {"root": str(root)})
            self._project(board)
            return deepcopy(board)

    def load(self):
        with self.lock():
            return deepcopy(self._load())

    def _mutation(self, fn):
        with self.lock():
            board = self._load()
            result = fn(board)
            self._save(board)
            return deepcopy(result)

    def add_task(self, task_id, owner, files, dependencies=(), risk="low", goal="", required_checks=()):
        def change(board):
            spec = {"id": task_id, "owner": owner, "files": list(files), "dependencies": list(dependencies), "risk": risk, "goal": goal, "required_checks": list(required_checks)}
            existing = next((t for t in board["tasks"] if t["id"] == task_id), None)
            if existing:
                need(all(existing[k] == v for k, v in spec.items()), "task_id_conflict")
                return existing
            task = {**spec, "status": "NEW", "branch": None, "worktree": None, "tests": [], "qa": None, "external_audit": None, "ci": None, "refs": {"base_sha": None, "head_sha": None, "pr": None}, "author_sessions": [], "updated_at": utcnow()}
            board["tasks"].append(task)
            return task
        return self._mutation(change)

    def update_task(self, task_id, *, dependencies=None, goal=None, required_checks=None):
        def change(board):
            task = _task(board, task_id)
            need(task["status"] == "NEW", "task_already_allocated")
            for key, value in (("dependencies", dependencies), ("goal", goal), ("required_checks", required_checks)):
                if value is not None:
                    task[key] = list(value) if key != "goal" else value
            task["updated_at"] = utcnow()
            return task
        return self._mutation(change)

    def cancel_task(self, task_id):
        def change(board):
            task = _task(board, task_id)
            need(not any(r["task_id"] == task_id and r["status"] == "RUNNING" for r in board["runs"]), "task_running")
            need(not any(task_id in t["dependencies"] and t["status"] != "CANCELLED" for t in board["tasks"]), "task_has_dependents")
            task["status"] = "CANCELLED"
            return task
        return self._mutation(change)

    def release_ownership(self, task_id, integration_sha, evidence):
        """Archive completed handoff without deleting branches or worktrees."""
        def change(board):
            task = _task(board, task_id)
            need(task["status"] == "READY_FOR_HUMAN_APPROVAL", "ready_task_required")
            need(not any(r["task_id"] == task_id and r["status"] == "RUNNING" for r in board["runs"]), "task_running")
            need(isinstance(integration_sha, str) and SHA.fullmatch(integration_sha), "full_integration_sha_required")
            need(isinstance(evidence, str) and evidence.strip(), "integration_evidence_required")
            self._candidate(task, task["refs"]["head_sha"])
            root = self._root()
            need(git(root, "rev-parse", "--verify", integration_sha + "^{commit}") == integration_sha, "integration_commit_missing")
            need(not git(root, "diff", "--name-only", task["refs"]["head_sha"], integration_sha, "--", *task["files"]), "integration_content_differs")
            task["refs"]["integration_sha"] = integration_sha
            task["handoff"] = {"evidence": evidence, "at": utcnow()}
            task["status"] = "INTEGRATED"
            return task
        return self._mutation(change)

    def _clean(self, root, allow_state=False):
        # --no-renames keeps each status record one path; no newline splitting.
        raw = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
        paths = [row[3:] for row in raw.split("\0") if row]
        need(not any(p not in STATE_FILES or not allow_state for p in paths), "dirty_worktree")

    def allocate(self, task_id, base_sha, worktree_parent=None):
        need(isinstance(base_sha, str) and SHA.fullmatch(base_sha), "full_base_sha_required")
        with self.lock():
            board = self._load()
            task = _task(board, task_id)
            need(task["status"] in {"NEW", "ALLOCATING", "ALLOCATED"}, "invalid_allocation_state")
            need(all(_task(board, d)["status"] in {"READY_FOR_HUMAN_APPROVAL", "INTEGRATED"} for d in task["dependencies"]), "dependencies_incomplete")
            root = self._root()
            self._clean(root, allow_state=True)
            need(git(root, "rev-parse", "--verify", base_sha + "^{commit}") == base_sha, "base_commit_missing")
            for dependency in task["dependencies"]:
                previous = _task(board, dependency)
                need(not git(root, "diff", "--name-only", previous["refs"]["head_sha"], base_sha, "--", *previous["files"]), "dependency_content_missing_from_base")
            for name in task["files"]:
                path = no_symlinks(root / name)
                need(not path.is_dir(), "exact_file_required")
                need(name not in STATE_FILES, "state_owned_by_a0")
            if task["branch"] is None:
                parent = no_symlinks(worktree_parent or (root.parent / "tariff-agent-worktrees"))
                need(not parent.is_relative_to(root), "worktree_must_be_outside_checkout")
                parent.mkdir(parents=True, exist_ok=True)
                slug = re.sub(r"[^a-z0-9]+", "-", task_id.lower()).strip("-")
                unique = slug + "-" + uuid.uuid4().hex[:10]
                task.update(branch=safe_branch("agent/" + PREFIX[task["owner"]] + "-" + unique), worktree=str(parent / unique), status="ALLOCATING")
                task["refs"]["base_sha"] = base_sha
                # Reservation is durable before git's filesystem side effects.
                self._save(board)
            need(task["refs"]["base_sha"] == base_sha, "base_change_forbidden")
            path = no_symlinks(task["worktree"])
            if path.exists():
                need(path.is_dir() and git(path, "branch", "--show-current") == task["branch"], "worktree_collision")
                need(Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")) == self.common, "worktree_repository_mismatch")
                self._clean(path)
                need(git(path, "rev-parse", "HEAD") == base_sha, "allocation_head_changed")
            else:
                branches = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/").splitlines()
                if task["branch"] in branches:
                    need(git(root, "rev-parse", "refs/heads/" + task["branch"]) == base_sha, "reserved_branch_changed")
                    git(root, "worktree", "add", str(path), task["branch"])
                else:
                    git(root, "worktree", "add", "-b", task["branch"], str(path), base_sha)
            task["status"] = "ALLOCATED"
            task["updated_at"] = utcnow()
            self._save(board)
            return deepcopy(task)

    def start(self, task_id, session_id, role=None):
        def change(board):
            task = _task(board, task_id)
            actual_role = role or task["owner"]
            need(actual_role in {task["owner"], "A5", "A6"} and SESSION_ID.fullmatch(session_id or ""), "invalid_session")
            existing = next((r for r in board["runs"] if r["session_id"] == session_id and r["status"] == "RUNNING"), None)
            if existing:
                need(existing["task_id"] == task_id and existing["role"] == actual_role and existing["status"] == "RUNNING", "session_id_conflict")
                return existing
            need(task["worktree"] is not None, "task_not_allocated")
            if actual_role == task["owner"]:
                need(task["status"] in {"ALLOCATED", "CHANGES_REQUESTED"}, "invalid_implementation_state")
                task["status"] = "IN_PROGRESS"
                if session_id not in task["author_sessions"]:
                    task["author_sessions"].append(session_id)
            elif actual_role == "A5":
                need(task["status"] == "IMPLEMENTED", "implementation_required")
                need(session_id not in task["author_sessions"], "independent_qa_required")
            else:
                need(task["status"] == "QA_PASSED", "qa_required")
            run = {"run_id": uuid.uuid4().hex, "session_id": session_id, "task_id": task_id, "head_sha": task["refs"]["head_sha"], "role": actual_role, "status": "RUNNING", "started_at": utcnow(), "updated_at": utcnow()}
            board["runs"].append(run)
            task["updated_at"] = utcnow()
            return run
        return self._mutation(change)

    def finish_session(self, session_id):
        def change(board):
            rows = [r for r in board["runs"] if r["session_id"] == session_id and r["status"] == "RUNNING"]
            if not rows:
                finished = [r for r in board["runs"] if r["session_id"] == session_id and r["status"] == "FINISHED"]
                need(finished, "session_not_found")
                return finished[-1]
            need(len(rows) == 1, "duplicate_running_session")
            rows[0].update(status="FINISHED", updated_at=utcnow())
            return rows[0]
        return self._mutation(change)

    def _candidate(self, task, head_sha):
        need(isinstance(head_sha, str) and SHA.fullmatch(head_sha), "full_head_sha_required")
        path = no_symlinks(task["worktree"] or "")
        need(path.is_dir(), "worktree_missing")
        need(Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")) == self.common, "worktree_repository_mismatch")
        need(git(path, "branch", "--show-current") == task["branch"], "worktree_branch_changed")
        self._clean(path)
        need(git(path, "rev-parse", "HEAD") == head_sha, "candidate_head_changed")
        # Subprocess git merge-base is read-only and rejects unrelated histories.
        need(git(path, "merge-base", task["refs"]["base_sha"], head_sha) == task["refs"]["base_sha"], "candidate_not_descendant")
        changed = set(filter(None, git(path, "diff", "--name-only", "--no-renames", "-z", task["refs"]["base_sha"], head_sha, "--").split("\0")))
        need(changed and changed <= set(task["files"]), "candidate_outside_file_ownership")
        for name in changed:
            no_symlinks(path / name)
        return path

    @staticmethod
    def _invalidate(task):
        task.update(status="CHANGES_REQUESTED", tests=[], qa=None, external_audit=None, ci=None, updated_at=utcnow())

    def implemented(self, task_id, head_sha, tests):
        checked_tests = _tests(tests)
        def change(board):
            task = _task(board, task_id)
            need(task["status"] not in {"NEW", "ALLOCATING", "CANCELLED", "INTEGRATED"}, "task_not_allocated")
            need(task["author_sessions"], "real_author_session_required")
            self._candidate(task, head_sha)
            self._invalidate(task)
            task["refs"]["head_sha"] = head_sha
            task["tests"] = {"head_sha": head_sha, "commands": checked_tests}
            task["status"] = "IMPLEMENTED"
            return task
        return self._mutation(change)

    def record_qa(self, task_id, head_sha, reviewer_session_id, tests, passed=True):
        checked_tests = _tests(tests) if passed else deepcopy(tests)
        def change(board):
            task = _task(board, task_id)
            self._candidate(task, head_sha)
            need(task["refs"]["head_sha"] == head_sha and task["status"] == "IMPLEMENTED", "stale_or_missing_implementation")
            need(reviewer_session_id not in task["author_sessions"], "independent_qa_required")
            need(any(r["session_id"] == reviewer_session_id and r["task_id"] == task_id and r["role"] == "A5" and r.get("head_sha") == head_sha for r in board["runs"]), "independent_qa_session_required")
            task["qa"] = {"head_sha": head_sha, "reviewer_session_id": reviewer_session_id, "status": "PASSED" if passed else "FAILED", "commands": checked_tests}
            task["status"] = "QA_PASSED" if passed else "CHANGES_REQUESTED"
            task["updated_at"] = utcnow()
            return task
        return self._mutation(change)

    def record_audit(self, task_id, head_sha, status, evidence_ref, reviewer="A6"):
        def change(board):
            task = _task(board, task_id)
            self._candidate(task, head_sha)
            need(task["status"] in {"QA_PASSED", "CI_PENDING"} and task["qa"] and task["qa"]["status"] == "PASSED" and task["refs"]["head_sha"] == head_sha, "current_qa_required")
            need(status in {"PASSED", "UNAVAILABLE", "FAILED", "NOT_REQUIRED"}, "invalid_audit_status")
            availability = None
            if status == "PASSED":
                _audit_passed(task, head_sha, evidence_ref)
            elif status == "UNAVAILABLE":
                availability = _audit_unavailable(task, head_sha, evidence_ref)
            else:
                need(isinstance(evidence_ref, str) and evidence_ref.strip(), "audit_evidence_required")
            need(status != "NOT_REQUIRED" or task["risk"] in {"low", "medium"}, "high_risk_audit_required")
            need(reviewer == "A6", "external_auditor_required")
            task["external_audit"] = {"head_sha": head_sha, "status": status, "evidence_ref": deepcopy(evidence_ref), "reviewer": reviewer}
            if availability:
                task["external_audit"]["availability"] = availability
                task["external_audit"]["rationale"] = "Optional A6 not configured; no Claude audit performed." if availability == "NOT_CONFIGURED" else "Audit unavailable; this is not a passed external audit."
            task["status"] = "AUDIT_PASSED" if status in {"PASSED", "NOT_REQUIRED"} else "CHANGES_REQUESTED" if status == "FAILED" else "CI_PENDING"
            task["updated_at"] = utcnow()
            return task
        return self._mutation(change)

    def record_ci(self, task_id, head_sha, checks):
        def change(board):
            task = _task(board, task_id)
            self._candidate(task, head_sha)
            need(task["refs"]["head_sha"] == head_sha, "stale_ci_head")
            need(task["qa"] and task["qa"]["status"] == "PASSED" and task["qa"]["head_sha"] == head_sha, "current_qa_required")
            audit = task["external_audit"]
            need(audit and audit["head_sha"] == head_sha, "audit_state_required")
            need(isinstance(checks, list) and checks and task["required_checks"], "required_ci_checks_missing")
            need(all(isinstance(c, dict) and isinstance(c.get("name"), str) for c in checks), "invalid_ci_checks")
            need(len({c["name"] for c in checks}) == len(checks), "duplicate_ci_check")
            by_name = {c["name"]: c for c in checks}
            need(set(task["required_checks"]) <= set(by_name), "required_ci_checks_missing")
            for check in checks:
                need(check.get("head_sha") == head_sha, "stale_ci_check")
                need(check.get("conclusion") == "success", "ci_not_successful")
                need(type(check.get("run_id")) is int and check["run_id"] > 0 and check.get("url") == f"https://github.com/{REPOSITORY}/actions/runs/{check['run_id']}", "ci_provenance_required")
            task["ci"] = {"head_sha": head_sha, "checks": deepcopy(checks), "status": "PASSED"}
            unresolved = any(f["task_id"] == task_id and f["status"] in {"UNVALIDATED", "CONFIRMED"} for f in board["findings"])
            audit_ok = audit["status"] in {"PASSED", "NOT_REQUIRED"} or (audit["status"] == "UNAVAILABLE" and (task["risk"] in {"low", "medium"} or _audit_unavailable(task, head_sha, audit["evidence_ref"]) == "NOT_CONFIGURED"))
            task["status"] = "READY_FOR_HUMAN_APPROVAL" if audit_ok and not unresolved else "CI_PENDING"
            task["updated_at"] = utcnow()
            return task
        return self._mutation(change)

    def add_finding(self, finding_id, task_id, reporter, summary, head_sha):
        def change(board):
            task = _task(board, task_id)
            need(task["status"] != "INTEGRATED", "create_followup_task_for_integrated_finding")
            need(ID.fullmatch(finding_id or "") and isinstance(summary, str) and summary.strip(), "invalid_finding")
            need(reporter in ROLES | {"A0"} and SHA.fullmatch(head_sha or ""), "invalid_finding_context")
            row = {"id": finding_id, "task_id": task_id, "reporter": reporter, "summary": summary, "head_sha": head_sha}
            existing = next((f for f in board["findings"] if f["id"] == finding_id), None)
            if existing:
                need(all(existing[k] == v for k, v in row.items()), "finding_id_conflict")
                return existing
            row.update(status="UNVALIDATED", validation=None)
            board["findings"].append(row)
            if task["status"] == "READY_FOR_HUMAN_APPROVAL":
                task["status"] = "CI_PENDING"
            return row
        return self._mutation(change)

    def validate_finding(self, finding_id, confirmed, evidence):
        def change(board):
            rows = [f for f in board["findings"] if f["id"] == finding_id]
            need(len(rows) == 1 and type(confirmed) is bool and isinstance(evidence, str) and evidence.strip(), "finding_validation_required")
            finding = rows[0]
            finding.update(status="CONFIRMED" if confirmed else "REJECTED", validation={"validator": "A0", "evidence": evidence, "at": utcnow()})
            if confirmed:
                self._invalidate(_task(board, finding["task_id"]))
            return finding
        return self._mutation(change)

    def resolve_finding(self, finding_id, head_sha, evidence):
        def change(board):
            rows = [f for f in board["findings"] if f["id"] == finding_id]
            need(len(rows) == 1 and rows[0]["status"] == "CONFIRMED", "confirmed_finding_required")
            finding = rows[0]
            task = _task(board, finding["task_id"])
            self._candidate(task, head_sha)
            need(task["refs"]["head_sha"] == head_sha and head_sha != finding["head_sha"], "new_fix_commit_required")
            need(isinstance(evidence, str) and evidence.strip(), "fix_evidence_required")
            finding.update(status="RESOLVED", resolution={"head_sha": head_sha, "evidence": evidence, "validator": "A0"})
            return finding
        return self._mutation(change)

    def recover(self, stale_after_seconds=3600):
        need(type(stale_after_seconds) is int and stale_after_seconds > 0, "invalid_stale_interval")
        with self.lock():
            board = self._load()
            report = {"state_source": ".ai/TASK_BOARD.json", "stale_sessions": [], "worktree_issues": [], "ready_tasks": [], "duplicate_launch_authorized": False}
            now = datetime.now(timezone.utc)
            changed = False
            for run in board["runs"]:
                if run["status"] == "RUNNING" and (now - datetime.fromisoformat(run["updated_at"])).total_seconds() > stale_after_seconds:
                    report["stale_sessions"].append(run["session_id"])
            for task in board["tasks"]:
                if task["worktree"] and task["status"] not in {"CANCELLED", "INTEGRATED"}:
                    try:
                        path = no_symlinks(task["worktree"])
                        need(path.is_dir(), "worktree_missing")
                        need(Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")) == self.common, "worktree_repository_mismatch")
                        need(git(path, "branch", "--show-current") == task["branch"], "worktree_branch_changed")
                        self._clean(path)
                        if task["refs"]["head_sha"]:
                            need(git(path, "rev-parse", "HEAD") == task["refs"]["head_sha"], "candidate_head_changed")
                    except (PolicyError, FileNotFoundError):
                        report["worktree_issues"].append(task["id"])
                        if task["qa"] or task["ci"] or task["external_audit"]:
                            self._invalidate(task)
                            changed = True
                if task["status"] == "READY_FOR_HUMAN_APPROVAL":
                    report["ready_tasks"].append(task["id"])
            if changed:
                self._save(board)
            else:
                self._project(board)
            report["board"] = deepcopy(board)
            return report
