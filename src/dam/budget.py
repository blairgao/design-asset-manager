"""Per-firm monthly enrichment budget (DESIGN.md section 11)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from dam.config import get_settings
from dam.models import EnrichmentUsage, Firm


def current_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


async def over_budget(session: AsyncSession, firm_id: uuid.UUID) -> bool:
    firm = await session.get(Firm, firm_id)
    limit = (
        firm.enrichment_budget_tokens
        if firm and firm.enrichment_budget_tokens
        else get_settings().monthly_enrichment_budget_tokens
    )
    usage = await session.get(EnrichmentUsage, (firm_id, current_month()))
    if usage is None:
        return False
    return usage.input_tokens + usage.output_tokens >= limit


async def record_usage(
    session: AsyncSession, firm_id: uuid.UUID, input_tokens: int, output_tokens: int
) -> None:
    key = (firm_id, current_month())
    usage = await session.get(EnrichmentUsage, key)
    if usage is None:
        usage = EnrichmentUsage(firm_id=firm_id, month=key[1])
        session.add(usage)
    usage.input_tokens += input_tokens
    usage.output_tokens += output_tokens
    usage.assets_enriched += 1
