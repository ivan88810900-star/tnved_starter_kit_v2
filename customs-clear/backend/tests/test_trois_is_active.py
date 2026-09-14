"""Тесты is_active для trois_registry."""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app.services import trois_registry_loader, trois_service
from app.services.trois_registry_sync import compute_trois_is_active


class TroisIsActiveTests(unittest.TestCase):
    def test_empty_valid_until_is_active(self) -> None:
        self.assertTrue(compute_trois_is_active(""))
        self.assertTrue(compute_trois_is_active(None))

    def test_future_date_is_active(self) -> None:
        future = date.today() + timedelta(days=30)
        vu = future.strftime("%Y.%m.%d")
        self.assertTrue(compute_trois_is_active(vu))

    def test_past_date_is_inactive(self) -> None:
        self.assertFalse(compute_trois_is_active("2010.12.31"))


class TroisRuntimeCacheInvalidationTests(unittest.TestCase):
    def test_full_reload_removes_keys_missing_from_new_db_snapshot(self) -> None:
        key = "db-only-delisted-test-brand"
        trois_service._LOCAL_CACHE[key] = trois_service._mk(key, "holder", "goods")
        trois_registry_loader._DB_CACHE_KEYS.add(key)
        query = MagicMock()
        query.filter.return_value.limit.return_value.all.return_value = []
        session = MagicMock()
        session.query.return_value = query
        session_cm = MagicMock()
        session_cm.__enter__.return_value = session
        session_cm.__exit__.return_value = False

        with (
            patch.object(trois_registry_loader, "count_db_brands", return_value=0),
            patch.object(trois_registry_loader, "SessionLocal", return_value=session_cm),
        ):
            trois_registry_loader.sync_db_to_local_cache(force=True)

        self.assertNotIn(key, trois_service._LOCAL_CACHE)
        self.assertNotIn(key, trois_registry_loader._DB_CACHE_KEYS)

    def test_revision_change_forces_reload_in_long_lived_process(self) -> None:
        revisions = iter(("rev-1", "rev-2"))
        old_loaded = trois_service._db_cache_loaded
        old_revision = trois_service._db_cache_revision
        trois_service._db_cache_loaded = True
        trois_service._db_cache_revision = "rev-1"
        try:
            with (
                patch.object(trois_service, "_current_db_cache_revision", side_effect=revisions),
                patch(
                    "app.services.trois_registry_loader.sync_db_to_local_cache"
                ) as reload_cache,
            ):
                trois_service._ensure_db_cache_loaded()
                reload_cache.assert_not_called()
                trois_service._ensure_db_cache_loaded()
                reload_cache.assert_called_once_with(force=True)
        finally:
            trois_service._db_cache_loaded = old_loaded
            trois_service._db_cache_revision = old_revision


if __name__ == "__main__":
    unittest.main()
