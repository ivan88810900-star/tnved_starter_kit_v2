"""
Иерархия кодов ТН ВЭД (4 → 6 → 10 знаков).

Реализация эндпоинта находится в `app.routers.codes` (маршрут GET /codes/hierarchy).
Этот модуль оставлен для явного пути app.api.codes по запросу инструментов/доков.
"""

from ..routers.codes import build_hierarchy_from_flat_hs_rows  # noqa: F401
