"""Synthetic structural fixtures only; not captured official HTML or current law."""
from app.services.ett_manifest import EXPECTED_CHAPTERS


def synthetic_index_html(*, omit: str | None = None, extra: str = "") -> bytes:
    # Nonstandard fictional filenames ensure no chapter URLs are guessed.
    rows = "\n".join(
        f'<tr><td><p>Группа&nbsp;{chapter}</p></td><td><a href="ru.2022/published-{chapter}-opaque.pdf">Описание {chapter}</a></td></tr>'
        for chapter in EXPECTED_CHAPTERS if chapter != omit
    )
    return ('''<!doctype html><html><head><meta charset="utf-8"></head><body>
<nav><a href="https://docs.eaeunion.org/">Правовой портал</a></nav>
<main><h1>ТН ВЭД ЕАЭС и ЕТТ ЕАЭС</h1>
<p>УТВЕРЖДЕНЫ<br>Решением Совета от 14 сентября 2021 г. № 80</p>
<p>(в ред. решений Коллегии Евразийской экономической комиссии
<a href="https://docs.eaeunion.org/docs/ru-ru/01232481/err_28042022_66">от 19.04.2022 № 66 с разъяснением</a>, от 11.08.2026 № 102,
решений Совета Евразийской экономической комиссии от 09.07.2026 № 76)</p>
<a href="/upload/files/catr/ett/interpretation.pdf">ОСНОВНЫЕ ПРАВИЛА ИНТЕРПРЕТАЦИИ ТН ВЭД</a>
<table><tbody><tr><td>РАЗДЕЛ I</td><td>Описание раздела</td></tr>''' + rows + '''</tbody></table>
<p><a href="ru.2022/Примечания к ТН ВЭД_11.05.2025.pdf">Примечания к единой Товарной номенклатуре внешнеэкономической деятельности Евразийского экономического союза&#8203;</a></p>
<p><a href="ru.2022/Примечания к ЕТТ_24.08.2026.pdf">Примечания к Единому таможенному тарифу Евразийского экономического союза</a>
<a href="ru.2022/Примечания к ЕТТ_08.02.2024.pdf">&#8203;&#8203;</a></p>''' + extra + '''
</main><footer><a href="https://docs.eaeunion.org/documents/1/2/">Unrelated footer document</a></footer>
</body></html>''').encode()
