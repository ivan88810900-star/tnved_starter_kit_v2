"""Извлечение путей к изображениям товаров для мультимодального анализа (MVP — локальные файлы)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class DocumentVisionExtractor:
    """
    Резолвит путь к изображению строки инвойса/упаковочного листа.

    Сейчас поддерживаются только явные пути в колонке (например ``Image_Path``) к ``.jpg`` / ``.png`` и др.
    Встраивание картинок из PDF/Excel — отдельный этап.
    """

    _IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"})

    def extract_image_for_row(
        self,
        filepath: str | Path,
        row_index: int | None = None,
        item_name: str | None = None,
    ) -> Path | None:
        """
        :param filepath: путь из ячейки (абсолютный или относительный к текущему рабочему каталогу).
        :param row_index: зарезервировано для будущей привязки к строке Excel.
        :param item_name: зарезервировано для дедупликации/логов.
        """
        _ = row_index, item_name
        p = Path(str(filepath).strip().strip('"').strip("'"))
        if not p.is_file():
            # Путь вида data/images/motor.jpg относительно каталога backend/
            backend_root = Path(__file__).resolve().parents[2]
            alt = backend_root / p
            if alt.is_file():
                p = alt
            else:
                return None
        suf = p.suffix.lower()
        if suf not in self._IMAGE_SUFFIXES:
            return None
        return p.resolve()
