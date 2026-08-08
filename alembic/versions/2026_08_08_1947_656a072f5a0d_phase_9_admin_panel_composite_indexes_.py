"""phase 9: admin panel composite indexes (active_ads, sold_ads, houses)

Revision ID: 656a072f5a0d
Revises:
Create Date: 2026-08-08 19:47:34.066199+00:00

Composite indexes per PLAN_ADMIN_PANEL_V1.md §"Phase 9 — индексы в БД".
These back the server-side pagination/sort/filter on /api/tables/{active,sold,houses}.

- active_ads(source, is_active, price, area, days_in_exposition) — filter by source,
  most listings are 'cian_active'; sort by price/area/days.
- sold_ads(source, sold_date, price, area) — filter by source, sort by sold_date desc
  (most common) and price/area.
- houses(source, year_built) — filter by source, sort by year_built asc.

CONCURRENTLY because the tables are large (sold_ads = 834 MB at the time of writing).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '656a072f5a0d'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CONCURRENTLY is not allowed inside a transaction in Postgres, so
    # we run each CREATE INDEX in its own autocommit context.
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_active_ads_phase9 "
            "ON public.active_ads (source, is_active, price, area, days_in_exposition)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sold_ads_phase9 "
            "ON public.sold_ads (source, sold_date, price, area)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_houses_phase9 "
            "ON public.houses (source, year_built)"
        )


def downgrade() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.idx_active_ads_phase9")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.idx_sold_ads_phase9")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.idx_houses_phase9")
