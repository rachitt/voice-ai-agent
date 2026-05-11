"""Seed a dev org + API key. Prints the raw key on stdout (only shown once)."""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.security import generate_api_key
from app.db.models import ApiKey, Org
from app.db.session import SessionLocal


async def main() -> None:
    async with SessionLocal() as db:
        org = (
            await db.execute(select(Org).where(Org.slug == "dev"))
        ).scalar_one_or_none()
        if not org:
            org = Org(name="Dev Org", slug="dev")
            db.add(org)
            await db.flush()

        raw, hashed = generate_api_key("sk_live")
        db.add(ApiKey(org_id=org.id, name="dev-bootstrap", prefix=raw[:12], key_hash=hashed))
        await db.commit()

        print(f"ORG_ID={org.id}")
        print(f"API_KEY={raw}")


if __name__ == "__main__":
    asyncio.run(main())
