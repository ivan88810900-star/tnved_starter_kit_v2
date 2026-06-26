# Интеграции внешних сервисов

## Нормативка и справочник кодов

| Документ | Описание |
|----------|----------|
| [NORMATIVE_PIPELINE.md](./NORMATIVE_PIPELINE.md) | **Единая стратегия**: тариф + ТН ВЭД + примечания + нетарифка; JSON-пакет, URL-синхронизация, API `/api/tnved/*` |
| [../ML_TRAINING_PIPELINE.md](../ML_TRAINING_PIPELINE.md) | Экспорт журнала в **JSONL** для fine-tune / внешнего ML (`export_training_pairs.py`) |
| [tws_by.md](./tws_by.md) | **TWS.BY** — бесплатная Excel-выгрузка ТН ВЭД + пошлины; импорт в БД через `POST /api/sources/import` |

## Альта-Софт (запасной внешний подсказчик)

Используйте после договора с Альтой, если нужны подсказки **«Товары и коды»** и **«Подбор кода»**. Основная база ставок в приложении — **импорт (TWS Excel, CSV, синхронизация ЕЭК и т.д.)**.

| Документ | Сервис |
|----------|--------|
| [alta_auth.md](./alta_auth.md) | Формулы MD5 для подписи запросов |
| [alta_tik_api.md](./alta_tik_api.md) | «Товары и коды» — `tik/xml` |
| [alta_apu_api.md](./alta_apu_api.md) | «Подбор кода» — `tnved/xml_apu` |

Backend прокси: **`/api/integrations/alta/`** — см. OpenAPI `/docs`. Тарифы — у [Альта-Софт](https://www.alta.ru/online-services/).
