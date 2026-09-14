from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier, Event, local
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.regulatory import RegulatorySourceReview
from app.services import regulatory_source_updates as updates


@pytest.fixture()
def review_store():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    RegulatorySourceReview.__table__.create(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with patch.object(updates, "SessionLocal", factory):
        yield factory
    engine.dispose()


def test_monthly_review_queue_is_complete_durable_and_idempotent(review_store) -> None:
    first = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    )
    assert first["durable"] is True
    assert first["contract_version"] == 1
    assert first["notification_required"] is True
    assert first["pending_count"] == 5
    assert set(first["created_source_ids"]) == {
        "official_sgr_ntm_v2_curated",
        "legacy_ntm_tr_catalog",
        "sanction_import_risks",
        "country_risks_geopolitics",
        "geo_special_duties_embargo",
    }
    assert {row["due_period"] for row in first["items"]} == {"2026-09"}
    assert set(first["managed_source_ids"]) == set(first["created_source_ids"])
    assert {len(row["evidence_sha256"]) for row in first["items"]} == {64}
    assert {row["evidence_generation"] for row in first["items"]} == {1}
    fixture_only = {
        row["source_id"]: row
        for row in first["items"]
        if not row["evidence_manifest"]["official_url"]
    }
    assert set(fixture_only) == {
        "sanction_import_risks",
        "country_risks_geopolitics",
        "geo_special_duties_embargo",
    }
    assert {
        row["evidence_scope"] for row in fixture_only.values()
    } == {"local_fixture_only_no_official_upstream"}

    repeated = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
    )
    assert repeated["created_source_ids"] == []
    assert set(repeated["carried_source_ids"]) == set(first["created_source_ids"])
    assert repeated["pending_count"] == 5
    assert {row["occurrence_count"] for row in repeated["items"]} == {2}

    # An unresolved September item is carried into the October notification,
    # not duplicated into a second pending row.
    carried = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
    )
    assert carried["pending_count"] == 5
    assert carried["created_source_ids"] == []
    assert {row["due_period"] for row in carried["items"]} == {"2026-09"}
    with review_store() as db:
        assert db.query(RegulatorySourceReview).count() == 5


def test_resolution_keeps_history_and_next_period_reopens(review_store) -> None:
    first = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    )
    for row in first["items"]:
        resolved = updates.resolve_regulatory_source_review(
            row["id"],
            authenticated_actor="admin-token:sha256:test",
            asserted_by="legal-reviewer",
            resolution_ref="#321",
            evidence_sha256=row["evidence_sha256"],
            evidence_generation=row["evidence_generation"],
            now=datetime(2026, 9, 3, 10, tzinfo=timezone.utc),
        )
        assert resolved["status"] == "resolved"

    assert updates.regulatory_review_queue_summary()["status"] == "clear"
    same_period = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 9, 4, 10, tzinfo=timezone.utc)
    )
    assert same_period["pending_count"] == 0
    assert same_period["created_source_ids"] == []

    next_period = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
    )
    assert next_period["pending_count"] == 5
    assert len(next_period["created_source_ids"]) == 5
    with review_store() as db:
        assert db.query(RegulatorySourceReview).count() == 10
        assert db.query(RegulatorySourceReview).filter_by(status="resolved").count() == 5


def test_resolution_is_auditable_and_conflicting_repeat_fails(review_store) -> None:
    item = updates._raise_scheduled_regulatory_reviews()["items"][0]
    first = updates.resolve_regulatory_source_review(
        item["id"],
        authenticated_actor="admin-token:sha256:test",
        asserted_by="reviewer",
        resolution_ref="#42",
        evidence_sha256=item["evidence_sha256"],
        evidence_generation=item["evidence_generation"],
    )
    repeated = updates.resolve_regulatory_source_review(
        item["id"],
        authenticated_actor="admin-token:sha256:test",
        asserted_by="reviewer",
        resolution_ref="#42",
        evidence_sha256=item["evidence_sha256"],
        evidence_generation=item["evidence_generation"],
    )
    assert repeated == first
    assert first["resolved_by"] == "admin-token:sha256:test"
    assert first["asserted_by"] == "reviewer"
    with pytest.raises(ValueError, match="different audit evidence"):
        updates.resolve_regulatory_source_review(
            item["id"],
            authenticated_actor="admin-token:sha256:other",
            asserted_by="other",
            resolution_ref="#999",
            evidence_sha256=item["evidence_sha256"],
            evidence_generation=item["evidence_generation"],
        )
    with pytest.raises(ValueError, match="authenticated_actor"):
        updates.resolve_regulatory_source_review(
            item["id"],
            authenticated_actor="",
            asserted_by="other",
            resolution_ref="#999",
            evidence_sha256=item["evidence_sha256"],
            evidence_generation=item["evidence_generation"],
        )
    with pytest.raises(ValueError, match="same-repository"):
        updates.resolve_regulatory_source_review(
            item["id"],
            authenticated_actor="admin-token:sha256:test",
            asserted_by="reviewer",
            resolution_ref="https://github.com/other/repository/issues/42",
            evidence_sha256=item["evidence_sha256"],
            evidence_generation=item["evidence_generation"],
        )
    pending = updates._raise_scheduled_regulatory_reviews()["items"][0]
    with pytest.raises(ValueError, match="evidence_generation does not match"):
        updates.resolve_regulatory_source_review(
            pending["id"],
            authenticated_actor="admin-token:sha256:test",
            asserted_by="reviewer",
            resolution_ref="#43",
            evidence_sha256=pending["evidence_sha256"],
            evidence_generation=pending["evidence_generation"] + 1,
        )


def test_evidence_binding_requires_manifest_bump_for_changed_local_bytes(
    tmp_path: Path,
) -> None:
    source = next(
        entry
        for entry in updates.REGULATORY_SOURCE_REGISTRY
        if entry.source_id == "sanction_import_risks"
    )
    artifact = tmp_path / "fixture.json"
    artifact.write_text('{"version":1}\n', encoding="utf-8")
    isolated = replace(source, local_paths=("fixture.json",), official_url="")
    generation_manifest = tmp_path / "regulatory_review_generations.json"

    def write_generation(generation: int) -> None:
        generation_manifest.write_text(
            json.dumps(
                {
                    "contract_version": 1,
                    "sources": {
                        source.source_id: {
                            "generation": generation,
                            "artifacts": [
                                {
                                    "path": "fixture.json",
                                    "sha256": hashlib.sha256(
                                        artifact.read_bytes()
                                    ).hexdigest(),
                                }
                            ],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    write_generation(1)
    with (
        patch.object(updates, "BACKEND_ROOT", tmp_path),
        patch.object(
            updates,
            "REVIEW_EVIDENCE_GENERATIONS_PATH",
            generation_manifest,
        ),
        patch.object(updates, "REGULATORY_SOURCE_REGISTRY", (isolated,)),
        patch.object(updates, "_LOCAL_RECONCILE", {source.source_id}),
    ):
        first = updates._source_evidence_binding(source.source_id)
        repeated = updates._source_evidence_binding(source.source_id)
        artifact.write_text('{"version":2}\n', encoding="utf-8")
        with pytest.raises(RuntimeError, match="changed without.*manifest update"):
            updates._source_evidence_binding(source.source_id)
        write_generation(2)
        changed = updates._source_evidence_binding(source.source_id)

    assert repeated == first
    assert changed["evidence_sha256"] != first["evidence_sha256"]
    assert first["evidence_generation"] == 1
    assert changed["evidence_generation"] == 2
    assert changed["evidence_scope"] == "local_fixture_only_no_official_upstream"
    assert "cannot establish current legal completeness" in changed["evidence_manifest"][
        "binding_limitation"
    ]


def test_changed_pending_snapshot_is_superseded_and_old_resolution_is_blocked(
    review_store,
) -> None:
    first = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    )
    item = first["items"][0]
    original_binding = updates._source_evidence_binding

    def changed_binding(source_id: str):
        binding = original_binding(source_id)
        if source_id == item["source_id"]:
            binding["evidence_sha256"] = "f" * 64
            binding["evidence_generation"] += 1
            binding["evidence_manifest"] = {
                **binding["evidence_manifest"],
                "test_revision": "changed",
            }
        return binding

    with patch.object(updates, "_source_evidence_binding", side_effect=changed_binding):
        reraised = updates._raise_scheduled_regulatory_reviews(
            now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
        )
        replacement = next(
            row for row in reraised["items"] if row["source_id"] == item["source_id"]
        )
        assert replacement["id"] != item["id"]
        assert replacement["evidence_sha256"] == "f" * 64
        assert item["source_id"] in reraised["superseded_source_ids"]
        with pytest.raises(ValueError, match="was superseded"):
            updates.resolve_regulatory_source_review(
                item["id"],
                authenticated_actor="admin-token:sha256:test",
                asserted_by="reviewer",
                resolution_ref="#42",
                evidence_sha256=item["evidence_sha256"],
                evidence_generation=item["evidence_generation"],
            )
        resolved = updates.resolve_regulatory_source_review(
            replacement["id"],
            authenticated_actor="admin-token:sha256:test",
            asserted_by="reviewer",
            resolution_ref="#43",
            evidence_sha256=replacement["evidence_sha256"],
            evidence_generation=replacement["evidence_generation"],
        )
        assert resolved["status"] == "resolved"

    with review_store() as db:
        preserved = db.get(RegulatorySourceReview, int(item["id"]))
        assert preserved is not None
        assert preserved.status == "superseded"
        assert preserved.evidence_sha256 == item["evidence_sha256"]
        assert preserved.superseded_at is not None
        assert preserved.superseded_by_evidence_sha256 == "f" * 64
        assert preserved.superseded_by_generation == replacement["evidence_generation"]


def test_resolution_rolls_back_if_local_bytes_change_during_cas(review_store) -> None:
    item = updates._raise_scheduled_regulatory_reviews()["items"][0]
    actual = updates._source_evidence_binding(item["source_id"])
    changed = {
        **actual,
        "evidence_sha256": "c" * 64,
        "evidence_generation": actual["evidence_generation"] + 1,
        "evidence_manifest": {
            **actual["evidence_manifest"],
            "test_revision": "changed-during-resolution",
        },
    }
    with patch.object(
        updates,
        "_source_evidence_binding",
        side_effect=[actual, changed],
    ):
        with pytest.raises(ValueError, match="changed during resolution"):
            updates.resolve_regulatory_source_review(
                item["id"],
                authenticated_actor="admin-token:sha256:test",
                asserted_by="reviewer",
                resolution_ref="#43",
                evidence_sha256=item["evidence_sha256"],
                evidence_generation=item["evidence_generation"],
            )

    with review_store() as db:
        preserved = db.get(RegulatorySourceReview, int(item["id"]))
        assert preserved is not None
        assert preserved.status == "pending"
        assert preserved.resolved_at is None
        assert preserved.resolved_by == ""


def test_resolution_rejects_bytes_changed_before_queue_refresh(review_store) -> None:
    item = updates._raise_scheduled_regulatory_reviews()["items"][0]
    actual = updates._source_evidence_binding

    def changed_binding(source_id: str):
        binding = actual(source_id)
        if source_id == item["source_id"]:
            binding["evidence_sha256"] = "9" * 64
        return binding

    with patch.object(updates, "_source_evidence_binding", side_effect=changed_binding):
        with pytest.raises(ValueError, match="local evidence changed after"):
            updates.resolve_regulatory_source_review(
                item["id"],
                authenticated_actor="admin-token:sha256:test",
                asserted_by="reviewer",
                resolution_ref="#44",
                evidence_sha256=item["evidence_sha256"],
                evidence_generation=item["evidence_generation"],
            )

    with review_store() as db:
        preserved = db.get(RegulatorySourceReview, int(item["id"]))
        assert preserved is not None
        assert preserved.status == "pending"


def test_changed_snapshot_after_resolution_appends_linked_pending_item(review_store) -> None:
    first = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    )
    item = first["items"][0]
    updates.resolve_regulatory_source_review(
        item["id"],
        authenticated_actor="admin-token:sha256:test",
        asserted_by="reviewer",
        resolution_ref="#42",
        evidence_sha256=item["evidence_sha256"],
        evidence_generation=item["evidence_generation"],
    )
    original_binding = updates._source_evidence_binding

    def changed_binding(source_id: str):
        binding = original_binding(source_id)
        if source_id == item["source_id"]:
            binding["evidence_sha256"] = "e" * 64
            binding["evidence_generation"] += 1
        return binding

    with patch.object(updates, "_source_evidence_binding", side_effect=changed_binding):
        reraised = updates._raise_scheduled_regulatory_reviews(
            now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
        )

    replacement = next(
        row for row in reraised["items"] if row["source_id"] == item["source_id"]
    )
    assert replacement["id"] != item["id"]
    assert replacement["evidence_sha256"] == "e" * 64
    assert item["source_id"] in reraised["superseded_source_ids"]

    with review_store() as db:
        same_source = db.query(RegulatorySourceReview).filter_by(
            source_id=item["source_id"]
        ).all()
        assert len(same_source) == 2
        predecessor = next(row for row in same_source if row.id == item["id"])
        successor = next(row for row in same_source if row.id != item["id"])
        assert predecessor.status == "resolved"
        assert predecessor.evidence_sha256 == item["evidence_sha256"]
        assert predecessor.superseded_at is not None
        assert predecessor.superseded_by_evidence_sha256 == "e" * 64
        assert predecessor.superseded_by_generation == replacement["evidence_generation"]
        assert successor.status == "pending"
        assert successor.evidence_sha256 == "e" * 64


def test_old_replica_cannot_downgrade_newer_pending_evidence(review_store) -> None:
    initial = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    )
    item = initial["items"][-1]
    original_binding = updates._source_evidence_binding

    def newer_binding(source_id: str):
        binding = original_binding(source_id)
        if source_id == item["source_id"]:
            binding["evidence_sha256"] = "b" * 64
            binding["evidence_generation"] += 1
            binding["evidence_manifest"] = {
                **binding["evidence_manifest"],
                "test_revision": "new-replica",
            }
        return binding

    with patch.object(updates, "_source_evidence_binding", side_effect=newer_binding):
        advanced = updates._raise_scheduled_regulatory_reviews(
            now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
        )
    newer = next(
        row for row in advanced["items"] if row["source_id"] == item["source_id"]
    )
    assert newer["evidence_sha256"] == "b" * 64

    # This process still exposes the original (older) checked-in bytes.  The
    # monthly pass must fail visibly without replacing digest B with digest A;
    # mutations to the other four sources must roll back with it.
    with pytest.raises(
        updates.RegulatoryReviewEvidenceConflict,
        match="historically superseded evidence reappeared",
    ):
        updates._raise_scheduled_regulatory_reviews(
            now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
        )

    with review_store() as db:
        predecessor = db.get(RegulatorySourceReview, int(item["id"]))
        successor = db.get(RegulatorySourceReview, int(newer["id"]))
        assert predecessor is not None
        assert successor is not None
        assert predecessor.status == "superseded"
        assert predecessor.evidence_sha256 == item["evidence_sha256"]
        assert predecessor.superseded_by_evidence_sha256 == "b" * 64
        assert predecessor.superseded_by_generation == newer["evidence_generation"]
        assert successor.status == "pending"
        assert successor.evidence_sha256 == "b" * 64
        assert {
            int(row.occurrence_count)
            for row in db.query(RegulatorySourceReview).all()
            if row.source_id != item["source_id"]
        } == {2}


def test_same_generation_with_different_digest_fails_closed(review_store) -> None:
    initial = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    )
    item = initial["items"][-1]
    original_binding = updates._source_evidence_binding

    def forked_binding(source_id: str):
        binding = original_binding(source_id)
        if source_id == item["source_id"]:
            binding["evidence_sha256"] = "6" * 64
            binding["evidence_manifest"] = {
                **binding["evidence_manifest"],
                "test_revision": "same-generation-fork",
            }
        return binding

    with patch.object(updates, "_source_evidence_binding", side_effect=forked_binding):
        with pytest.raises(
            updates.RegulatoryReviewEvidenceConflict,
            match="generation must increase",
        ):
            updates._raise_scheduled_regulatory_reviews(
                now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
            )

    with review_store() as db:
        rows = db.query(RegulatorySourceReview).all()
        assert len(rows) == 5
        assert {row.status for row in rows} == {"pending"}
        assert {int(row.occurrence_count) for row in rows} == {1}


def test_unseen_stale_generation_cannot_downgrade_newer_pending_evidence(
    review_store,
) -> None:
    initial = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    )
    item = initial["items"][-1]
    original_binding = updates._source_evidence_binding

    def generated_binding(source_id: str, *, digest: str, generation: int):
        binding = original_binding(source_id)
        if source_id == item["source_id"]:
            binding["evidence_sha256"] = digest * 64
            binding["evidence_generation"] = generation
            binding["evidence_manifest"] = {
                **binding["evidence_manifest"],
                "evidence_generation": generation,
                "test_revision": f"generation-{generation}",
            }
        return binding

    with patch.object(
        updates,
        "_source_evidence_binding",
        side_effect=lambda source_id: generated_binding(
            source_id,
            digest="c",
            generation=3,
        ),
    ):
        advanced = updates._raise_scheduled_regulatory_reviews(
            now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
        )
    current = next(
        row for row in advanced["items"] if row["source_id"] == item["source_id"]
    )
    assert current["evidence_generation"] == 3

    # Digest B/generation 2 was never persisted, so a digest-history-only gate
    # cannot recognize it as stale. The monotonic generation contract must.
    with patch.object(
        updates,
        "_source_evidence_binding",
        side_effect=lambda source_id: generated_binding(
            source_id,
            digest="b",
            generation=2,
        ),
    ):
        with pytest.raises(
            updates.RegulatoryReviewEvidenceConflict,
            match="generation must increase",
        ):
            updates._raise_scheduled_regulatory_reviews(
                now=datetime(2026, 9, 3, 10, tzinfo=timezone.utc)
            )

    with review_store() as db:
        lineage = (
            db.query(RegulatorySourceReview)
            .filter_by(source_id=item["source_id"])
            .order_by(RegulatorySourceReview.id.asc())
            .all()
        )
        assert [row.evidence_generation for row in lineage] == [1, 3]
        assert [row.status for row in lineage] == ["superseded", "pending"]
        assert lineage[0].superseded_by_generation == 3
        assert all(row.evidence_sha256 != "b" * 64 for row in lineage)
        assert {
            int(row.occurrence_count)
            for row in db.query(RegulatorySourceReview).all()
            if row.source_id != item["source_id"]
        } == {2}


def test_supersession_rolls_back_if_successor_cannot_be_created(review_store) -> None:
    initial = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    )
    item = initial["items"][-1]
    original_binding = updates._source_evidence_binding

    def changed_binding(source_id: str):
        binding = original_binding(source_id)
        if source_id == item["source_id"]:
            binding["evidence_sha256"] = "7" * 64
            binding["evidence_generation"] += 1
        return binding

    with (
        patch.object(updates, "_source_evidence_binding", side_effect=changed_binding),
        patch.object(
            updates,
            "_new_pending_review",
            side_effect=RuntimeError("successor insert unavailable"),
        ),
    ):
        with pytest.raises(RuntimeError, match="successor insert unavailable"):
            updates._raise_scheduled_regulatory_reviews(
                now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
            )

    with review_store() as db:
        rows = db.query(RegulatorySourceReview).all()
        assert len(rows) == 5
        assert {row.status for row in rows} == {"pending"}
        assert {int(row.occurrence_count) for row in rows} == {1}
        assert {str(row.superseded_by_evidence_sha256) for row in rows} == {""}
        assert {row.superseded_by_generation for row in rows} == {None}
        preserved = db.get(RegulatorySourceReview, int(item["id"]))
        assert preserved is not None
        assert preserved.evidence_sha256 == item["evidence_sha256"]


def test_resolution_between_commit_and_summary_does_not_false_fail(review_store) -> None:
    initial = updates._raise_scheduled_regulatory_reviews(
        now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    )
    item = initial["items"][0]
    original_summary = updates.regulatory_review_queue_summary
    intercepted = False

    def resolve_then_read_summary():
        nonlocal intercepted
        if not intercepted:
            intercepted = True
            updates.resolve_regulatory_source_review(
                item["id"],
                authenticated_actor="admin-token:sha256:test",
                asserted_by="summary-race-reviewer",
                resolution_ref="#909",
                evidence_sha256=item["evidence_sha256"],
                evidence_generation=item["evidence_generation"],
            )
        return original_summary()

    with patch.object(
        updates,
        "regulatory_review_queue_summary",
        side_effect=resolve_then_read_summary,
    ):
        reraised = updates._raise_scheduled_regulatory_reviews(
            now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
        )

    assert reraised["status"] == "review_required"
    assert reraised["pending_count"] == 4
    assert item["source_id"] not in reraised["pending_source_ids"]
    with review_store() as db:
        resolved = db.get(RegulatorySourceReview, int(item["id"]))
        assert resolved is not None
        assert resolved.status == "resolved"
        assert resolved.occurrence_count == 2


def test_refresh_cas_rolls_back_all_sources_when_resolution_wins(tmp_path: Path) -> None:
    """A refresh losing to resolution retries without mutating the audit row.

    The hook deterministically pauses after the refresh loaded the pending row
    but before its CAS.  Rolling back that SQLite read transaction models the
    READ COMMITTED statement boundary used by PostgreSQL and lets the resolver
    commit from a genuinely independent Session/thread.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'refresh-resolve-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    RegulatorySourceReview.__table__.create(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    loaded = Event()
    resolved = Event()
    intercepted = Event()

    with patch.object(updates, "SessionLocal", factory):
        initial = updates._raise_scheduled_regulatory_reviews(
            now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
        )
        # Pause the last source so four earlier CAS updates have already run;
        # their counters prove the lost transaction was fully rolled back.
        item = initial["items"][-1]
        original_cas = updates._refresh_pending_review_with_cas

        def pause_before_first_cas(db, **kwargs):
            if (
                int(kwargs["pending_id"]) == int(item["id"])
                and not intercepted.is_set()
            ):
                intercepted.set()
                # End SQLite's snapshot while retaining the primitive ID and
                # digest already passed by the queue scan.
                db.rollback()
                loaded.set()
                assert resolved.wait(timeout=10)
            return original_cas(db, **kwargs)

        def run_refresh():
            with patch.object(
                updates,
                "_refresh_pending_review_with_cas",
                side_effect=pause_before_first_cas,
            ):
                return updates._raise_scheduled_regulatory_reviews(
                    now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
                )

        def resolve_old_snapshot():
            assert loaded.wait(timeout=10)
            try:
                return updates.resolve_regulatory_source_review(
                    item["id"],
                    authenticated_actor="admin-token:sha256:test",
                    asserted_by="race-reviewer",
                    resolution_ref="#808",
                    evidence_sha256=item["evidence_sha256"],
                    evidence_generation=item["evidence_generation"],
                    now=datetime(2026, 9, 2, 10, 1, tzinfo=timezone.utc),
                )
            finally:
                resolved.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            refresh_future = executor.submit(run_refresh)
            resolve_future = executor.submit(resolve_old_snapshot)
            resolved_row = resolve_future.result(timeout=15)
            refreshed = refresh_future.result(timeout=15)

        assert resolved_row["status"] == "resolved"
        replacements = [
            row
            for row in refreshed["items"]
            if row["source_id"] == item["source_id"]
        ]
        assert replacements == []
        assert item["source_id"] in refreshed["already_reviewed_source_ids"]
        assert {
            row["occurrence_count"]
            for row in refreshed["items"]
            if row["source_id"] != item["source_id"]
        } == {2}

        with factory() as db:
            original = db.get(RegulatorySourceReview, int(item["id"]))
            assert original is not None
            assert original.status == "resolved"
            assert original.evidence_sha256 == item["evidence_sha256"]
            assert original.resolved_by == "admin-token:sha256:test"
            assert original.resolution_ref == "#808"

    engine.dispose()


def test_changed_refresh_after_concurrent_resolution_appends_successor(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'changed-refresh-resolve-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    RegulatorySourceReview.__table__.create(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    loaded = Event()
    resolved = Event()
    intercepted = Event()
    thread_state = local()

    with patch.object(updates, "SessionLocal", factory):
        initial = updates._raise_scheduled_regulatory_reviews(
            now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
        )
        item = initial["items"][-1]
        original_binding = updates._source_evidence_binding
        original_cas = updates._refresh_pending_review_with_cas

        def replica_binding(source_id: str):
            binding = original_binding(source_id)
            if (
                source_id == item["source_id"]
                and getattr(thread_state, "new_replica", False)
            ):
                binding["evidence_sha256"] = "d" * 64
                binding["evidence_generation"] += 1
                binding["evidence_manifest"] = {
                    **binding["evidence_manifest"],
                    "test_revision": "successor-d",
                }
            return binding

        def pause_before_first_cas(db, **kwargs):
            if (
                int(kwargs["pending_id"]) == int(item["id"])
                and not intercepted.is_set()
            ):
                intercepted.set()
                db.rollback()
                loaded.set()
                assert resolved.wait(timeout=10)
            return original_cas(db, **kwargs)

        def run_changed_refresh():
            thread_state.new_replica = True
            return updates._raise_scheduled_regulatory_reviews(
                now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
            )

        def resolve_predecessor():
            assert loaded.wait(timeout=10)
            try:
                return updates.resolve_regulatory_source_review(
                    item["id"],
                    authenticated_actor="admin-token:sha256:test",
                    asserted_by="race-reviewer",
                    resolution_ref="#810",
                    evidence_sha256=item["evidence_sha256"],
                    evidence_generation=item["evidence_generation"],
                )
            finally:
                resolved.set()

        with (
            patch.object(
                updates,
                "_source_evidence_binding",
                side_effect=replica_binding,
            ),
            patch.object(
                updates,
                "_refresh_pending_review_with_cas",
                side_effect=pause_before_first_cas,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            refresh_future = executor.submit(run_changed_refresh)
            resolve_future = executor.submit(resolve_predecessor)
            resolved_row = resolve_future.result(timeout=15)
            refreshed = refresh_future.result(timeout=15)

        assert resolved_row["status"] == "resolved"
        successor = next(
            row for row in refreshed["items"] if row["source_id"] == item["source_id"]
        )
        assert successor["evidence_sha256"] == "d" * 64
        with factory() as db:
            predecessor = db.get(RegulatorySourceReview, int(item["id"]))
            current = db.get(RegulatorySourceReview, int(successor["id"]))
            assert predecessor is not None
            assert current is not None
            assert predecessor.status == "resolved"
            assert predecessor.evidence_sha256 == item["evidence_sha256"]
            assert predecessor.superseded_by_evidence_sha256 == "d" * 64
            assert predecessor.superseded_by_generation == successor[
                "evidence_generation"
            ]
            assert current.status == "pending"
            assert current.evidence_sha256 == "d" * 64
            assert {
                int(row.occurrence_count)
                for row in db.query(RegulatorySourceReview).all()
                if row.source_id != item["source_id"]
            } == {2}

    engine.dispose()


def test_concurrent_changed_refreshes_form_one_linear_successor_chain(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent-refresh-chain.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    RegulatorySourceReview.__table__.create(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    b_loaded = Event()
    c_loaded = Event()
    b_done = Event()
    thread_state = local()

    with patch.object(updates, "SessionLocal", factory):
        initial = updates._raise_scheduled_regulatory_reviews(
            now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
        )
        item = initial["items"][0]
        original_binding = updates._source_evidence_binding
        original_cas = updates._refresh_pending_review_with_cas

        def replica_binding(source_id: str):
            binding = original_binding(source_id)
            digest = getattr(thread_state, "digest", "")
            if source_id == item["source_id"] and digest:
                binding["evidence_sha256"] = digest * 64
                binding["evidence_generation"] = 2 if digest == "b" else 3
                binding["evidence_manifest"] = {
                    **binding["evidence_manifest"],
                    "test_revision": f"successor-{digest}",
                }
            return binding

        def order_first_cas(db, **kwargs):
            digest = getattr(thread_state, "digest", "")
            if (
                int(kwargs["pending_id"]) == int(item["id"])
                and not getattr(thread_state, "paused", False)
            ):
                thread_state.paused = True
                db.rollback()
                if digest == "b":
                    b_loaded.set()
                    assert c_loaded.wait(timeout=10)
                elif digest == "c":
                    c_loaded.set()
                    assert b_loaded.wait(timeout=10)
                    assert b_done.wait(timeout=10)
            return original_cas(db, **kwargs)

        def run_replica(digest: str):
            thread_state.digest = digest
            try:
                return updates._raise_scheduled_regulatory_reviews(
                    now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
                )
            finally:
                if digest == "b":
                    b_done.set()

        with (
            patch.object(
                updates,
                "_source_evidence_binding",
                side_effect=replica_binding,
            ),
            patch.object(
                updates,
                "_refresh_pending_review_with_cas",
                side_effect=order_first_cas,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            b_future = executor.submit(run_replica, "b")
            c_future = executor.submit(run_replica, "c")
            b_result = b_future.result(timeout=15)
            c_result = c_future.result(timeout=15)

        assert next(
            row for row in b_result["items"] if row["source_id"] == item["source_id"]
        )["evidence_sha256"] == "b" * 64
        assert next(
            row for row in c_result["items"] if row["source_id"] == item["source_id"]
        )["evidence_sha256"] == "c" * 64
        with factory() as db:
            lineage = (
                db.query(RegulatorySourceReview)
                .filter_by(source_id=item["source_id"])
                .order_by(RegulatorySourceReview.id.asc())
                .all()
            )
            assert [row.status for row in lineage] == [
                "superseded",
                "superseded",
                "pending",
            ]
            assert [row.evidence_sha256 for row in lineage] == [
                item["evidence_sha256"],
                "b" * 64,
                "c" * 64,
            ]
            assert [row.evidence_generation for row in lineage] == [1, 2, 3]
            assert [row.superseded_by_evidence_sha256 for row in lineage] == [
                "b" * 64,
                "c" * 64,
                "",
            ]
            assert [row.superseded_by_generation for row in lineage] == [
                2,
                3,
                None,
            ]
            assert (
                db.query(RegulatorySourceReview)
                .filter_by(source_id=item["source_id"], status="pending")
                .count()
                == 1
            )

    engine.dispose()


def test_concurrent_higher_generation_blocks_unseen_stale_successor(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent-generation-regression.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    RegulatorySourceReview.__table__.create(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    c_loaded = Event()
    b_loaded = Event()
    c_done = Event()
    thread_state = local()

    with patch.object(updates, "SessionLocal", factory):
        initial = updates._raise_scheduled_regulatory_reviews(
            now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
        )
        # Pause the first managed source: the SQLite-only rollback used to end
        # the read snapshot then cannot discard prior per-source CAS writes.
        item = initial["items"][0]
        original_binding = updates._source_evidence_binding
        original_cas = updates._refresh_pending_review_with_cas

        def replica_binding(source_id: str):
            binding = original_binding(source_id)
            generation = getattr(thread_state, "generation", 0)
            if source_id == item["source_id"] and generation:
                digest = "c" if generation == 3 else "b"
                binding["evidence_sha256"] = digest * 64
                binding["evidence_generation"] = generation
                binding["evidence_manifest"] = {
                    **binding["evidence_manifest"],
                    "evidence_generation": generation,
                    "test_revision": f"generation-{generation}",
                }
            return binding

        def order_first_cas(db, **kwargs):
            generation = getattr(thread_state, "generation", 0)
            if (
                int(kwargs["pending_id"]) == int(item["id"])
                and not getattr(thread_state, "paused", False)
            ):
                thread_state.paused = True
                db.rollback()
                if generation == 3:
                    c_loaded.set()
                    assert b_loaded.wait(timeout=10)
                elif generation == 2:
                    b_loaded.set()
                    assert c_loaded.wait(timeout=10)
                    assert c_done.wait(timeout=10)
            return original_cas(db, **kwargs)

        def run_replica(generation: int):
            thread_state.generation = generation
            try:
                return updates._raise_scheduled_regulatory_reviews(
                    now=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
                )
            finally:
                if generation == 3:
                    c_done.set()

        with (
            patch.object(
                updates,
                "_source_evidence_binding",
                side_effect=replica_binding,
            ),
            patch.object(
                updates,
                "_refresh_pending_review_with_cas",
                side_effect=order_first_cas,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            c_future = executor.submit(run_replica, 3)
            b_future = executor.submit(run_replica, 2)
            current = c_future.result(timeout=15)
            with pytest.raises(
                updates.RegulatoryReviewEvidenceConflict,
                match="generation must increase",
            ):
                b_future.result(timeout=15)

        assert next(
            row for row in current["items"] if row["source_id"] == item["source_id"]
        )["evidence_generation"] == 3
        with factory() as db:
            lineage = (
                db.query(RegulatorySourceReview)
                .filter_by(source_id=item["source_id"])
                .order_by(RegulatorySourceReview.id.asc())
                .all()
            )
            assert [row.evidence_generation for row in lineage] == [1, 3]
            assert [row.status for row in lineage] == ["superseded", "pending"]
            assert all(row.evidence_sha256 != "b" * 64 for row in lineage)
            assert {
                int(row.occurrence_count)
                for row in db.query(RegulatorySourceReview).all()
                if row.source_id != item["source_id"]
            } == {2}

    engine.dispose()


def test_resolution_compare_and_set_allows_only_one_concurrent_winner(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent-review.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    RegulatorySourceReview.__table__.create(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with patch.object(updates, "SessionLocal", factory):
        item = updates._raise_scheduled_regulatory_reviews()["items"][0]
        barrier = Barrier(2)

        def attempt(asserted_by: str, reference: str) -> str:
            barrier.wait(timeout=5)
            try:
                updates.resolve_regulatory_source_review(
                    item["id"],
                    authenticated_actor="admin-token:sha256:test",
                    asserted_by=asserted_by,
                    resolution_ref=reference,
                    evidence_sha256=item["evidence_sha256"],
                    evidence_generation=item["evidence_generation"],
                )
            except ValueError:
                return "conflict"
            return "resolved"

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(attempt, "reviewer-a", "#101"),
                executor.submit(attempt, "reviewer-b", "#102"),
            ]
            results = sorted(future.result(timeout=10) for future in futures)

    engine.dispose()
    assert results == ["conflict", "resolved"]


def test_database_rejects_inconsistent_resolution_state(review_store) -> None:
    binding = updates._source_evidence_binding("sanction_import_risks")
    with review_store() as db:
        db.add(
            RegulatorySourceReview(
                source_id="sanction_import_risks",
                due_period="2026-09",
                strategy="local_reconcile",
                cadence="monthly",
                status="resolved",
                reason="test",
                evidence_sha256=binding["evidence_sha256"],
                evidence_generation=binding["evidence_generation"],
                evidence_scope=binding["evidence_scope"],
                evidence_manifest=binding["evidence_manifest"],
                resolved_at=datetime(2026, 9, 2, 10),
                resolved_by="",
                asserted_by="",
                resolution_ref="",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_database_rejects_superseded_row_without_successor_binding(review_store) -> None:
    binding = updates._source_evidence_binding("sanction_import_risks")
    with review_store() as db:
        db.add(
            RegulatorySourceReview(
                source_id="sanction_import_risks",
                due_period="2026-09",
                strategy="local_reconcile",
                cadence="monthly",
                status="superseded",
                reason="test",
                evidence_sha256=binding["evidence_sha256"],
                evidence_generation=binding["evidence_generation"],
                evidence_scope=binding["evidence_scope"],
                evidence_manifest=binding["evidence_manifest"],
                superseded_at=datetime(2026, 9, 2, 10),
                superseded_by_evidence_sha256="",
                superseded_by_generation=binding["evidence_generation"] + 1,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_database_rejects_non_increasing_supersession_generation(review_store) -> None:
    binding = updates._source_evidence_binding("sanction_import_risks")
    with review_store() as db:
        db.add(
            RegulatorySourceReview(
                source_id="sanction_import_risks",
                due_period="2026-09",
                strategy="local_reconcile",
                cadence="monthly",
                status="superseded",
                reason="test",
                evidence_sha256=binding["evidence_sha256"],
                evidence_generation=binding["evidence_generation"],
                evidence_scope=binding["evidence_scope"],
                evidence_manifest=binding["evidence_manifest"],
                superseded_at=datetime(2026, 9, 2, 10),
                superseded_by_evidence_sha256="f" * 64,
                superseded_by_generation=binding["evidence_generation"],
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_database_rejects_missing_supersession_generation(review_store) -> None:
    binding = updates._source_evidence_binding("sanction_import_risks")
    with review_store() as db:
        db.add(
            RegulatorySourceReview(
                source_id="sanction_import_risks",
                due_period="2026-09",
                strategy="local_reconcile",
                cadence="monthly",
                status="superseded",
                reason="test",
                evidence_sha256=binding["evidence_sha256"],
                evidence_generation=binding["evidence_generation"],
                evidence_scope=binding["evidence_scope"],
                evidence_manifest=binding["evidence_manifest"],
                superseded_at=datetime(2026, 9, 2, 10),
                superseded_by_evidence_sha256="f" * 64,
                superseded_by_generation=None,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_monthly_cycle_fails_closed_if_durable_queue_cannot_be_written(tmp_path: Path) -> None:
    @contextmanager
    def acquired_lock():
        yield True

    with (
        patch.object(updates, "_acquire_update_lock", acquired_lock),
        patch.object(
            updates,
            "_raise_scheduled_regulatory_reviews",
            side_effect=RuntimeError("review queue unavailable"),
        ),
        patch.object(updates, "LAST_REPORT_PATH", tmp_path / "last.json"),
    ):
        with pytest.raises(RuntimeError, match="review queue unavailable"):
            asyncio.run(updates.run_regulatory_update_cycle("monthly", apply_safe=True))

    assert not (tmp_path / "last.json").exists()


def test_monthly_review_queue_fails_closed_if_managed_policy_is_missing(review_store) -> None:
    policies = tuple(
        policy
        for policy in updates.UPDATE_POLICIES
        if policy.source_id != "legacy_ntm_tr_catalog"
    )
    with patch.object(updates, "UPDATE_POLICIES", policies):
        with pytest.raises(RuntimeError, match="differs from the managed source set"):
            updates._raise_scheduled_regulatory_reviews(
                now=datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
            )

    with review_store() as db:
        assert db.query(RegulatorySourceReview).count() == 0


def test_monthly_cycle_reports_pending_durable_notification(tmp_path: Path) -> None:
    @contextmanager
    def acquired_lock():
        yield True

    queue = {
        "durable": True,
        "pending_count": 5,
        "pending_source_ids": sorted(updates._LOCAL_RECONCILE),
        "notification_required": True,
        "items": [],
    }
    with (
        patch.object(updates, "_acquire_update_lock", acquired_lock),
        patch.object(updates, "_raise_scheduled_regulatory_reviews", return_value=queue),
        patch.object(updates, "LAST_REPORT_PATH", tmp_path / "last.json"),
    ):
        report = asyncio.run(
            updates.run_regulatory_update_cycle("monthly", apply_safe=True)
        )

    assert report["status"] == "review_required"
    assert report["review_queue"] == queue
    assert set(report["review_required_source_ids"]) == updates._LOCAL_RECONCILE
    assert (tmp_path / "last.json").is_file()
