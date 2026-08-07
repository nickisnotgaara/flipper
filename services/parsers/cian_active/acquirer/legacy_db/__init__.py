"""services.parsers.cian_active.acquirer.legacy_db - legacy DB layer для Cian.

Содержит:
    base.py       - SQLAlchemy models (CianFilter, CianActiveAd, CianSoldAd) + engine
    repository.py - DatabaseRepository (sync/async операции)

СТАТУС: legacy. Заменяется на packages/flipper_db (House/ActiveAd/SoldAd +
FlipperRepository). Миграция cian_active_ads → active_ads (source='cian_active')
планируется в следующих итерациях (см. PLAN.md).
"""
