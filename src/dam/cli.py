"""Admin CLI for operations without a UI yet: firms, memberships, re-enrichment.

uv run dam-admin create-firm --name "Studio Arc" --slug studio-arc --admin you@firm.com
uv run dam-admin add-member --firm studio-arc --email a@firm.com --role staff
uv run dam-admin seed-vocabulary
uv run dam-admin reenrich --firm studio-arc [--only-embeddings]
uv run dam-admin login-link --email you@firm.com
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from dam import auth
from dam.db import session_factory
from dam.enrichment.vocabulary import DEFAULT_VOCABULARY
from dam.models import Asset, AssetStatus, Firm, FirmRole, Membership, User
from dam.queue import enqueue_enrich
from dam.repositories.tags import get_or_create_tag


async def _get_firm(session, slug: str) -> Firm:
    firm = (await session.execute(select(Firm).where(Firm.slug == slug))).scalar_one_or_none()
    if firm is None:
        sys.exit(f"no firm with slug {slug!r}")
    return firm


async def _ensure_user(session, email: str) -> User:
    email = email.lower().strip()
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(email=email)
        session.add(user)
        await session.flush()
    return user


async def create_firm(args) -> None:
    async with session_factory()() as session:
        firm = Firm(name=args.name, slug=args.slug)
        session.add(firm)
        await session.flush()
        user = await _ensure_user(session, args.admin)
        session.add(Membership(user_id=user.id, firm_id=firm.id, role=FirmRole.admin))
        await session.commit()
        print(f"created firm {firm.id} ({firm.slug}); admin {user.email}")


async def add_member(args) -> None:
    async with session_factory()() as session:
        firm = await _get_firm(session, args.firm)
        user = await _ensure_user(session, args.email)
        m = await session.get(Membership, (user.id, firm.id))
        if m is None:
            session.add(Membership(user_id=user.id, firm_id=firm.id, role=FirmRole(args.role)))
        else:
            m.role = FirmRole(args.role)
        await session.commit()
        print(f"{user.email} is now {args.role} in {firm.slug}")


async def seed_vocabulary(args) -> None:
    async with session_factory()() as session:
        n = 0
        for ns, values in DEFAULT_VOCABULARY.items():
            for v in values:
                await get_or_create_tag(session, ns, v, None)
                n += 1
        await session.commit()
        print(f"seeded {n} global tags")


async def reenrich(args) -> None:
    async with session_factory()() as session:
        firm = await _get_firm(session, args.firm)
        stmt = select(Asset).where(
            Asset.firm_id == firm.id,
            Asset.deleted_at.is_(None),
            Asset.status.in_([AssetStatus.ready, AssetStatus.failed]),
        )
        assets = (await session.execute(stmt)).scalars().all()
        for a in assets:
            a.status = AssetStatus.processing
        await session.commit()
        for a in assets:
            await enqueue_enrich(a.id, a.kind, priority_low=True)
        print(f"queued {len(assets)} assets for re-enrichment")


async def login_link(args) -> None:
    async with session_factory()() as session:
        await _ensure_user(session, args.email)
        token = await auth.create_magic_link(session, args.email)
        await session.commit()
        print(auth.magic_link_url(token))


def main() -> None:
    parser = argparse.ArgumentParser(prog="dam-admin")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create-firm")
    p.add_argument("--name", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--admin", required=True, help="email of the first admin")
    p.set_defaults(fn=create_firm)

    p = sub.add_parser("add-member")
    p.add_argument("--firm", required=True, help="firm slug")
    p.add_argument("--email", required=True)
    p.add_argument("--role", choices=[r.value for r in FirmRole], default="staff")
    p.set_defaults(fn=add_member)

    p = sub.add_parser("seed-vocabulary")
    p.set_defaults(fn=seed_vocabulary)

    p = sub.add_parser("reenrich")
    p.add_argument("--firm", required=True)
    p.set_defaults(fn=reenrich)

    p = sub.add_parser("login-link")
    p.add_argument("--email", required=True)
    p.set_defaults(fn=login_link)

    args = parser.parse_args()
    asyncio.run(args.fn(args))


if __name__ == "__main__":
    main()
