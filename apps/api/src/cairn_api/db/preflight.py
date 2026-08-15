"""Startup checks that verify isolation is actually in force.

Misconfigured DB URLs disable RLS without raising, so these properties are
asserted at boot and the process refuses to start if they fail.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cairn_api.db.session import get_engine, get_platform_engine


class PreflightError(RuntimeError):
    """A required database property is not in force."""


@dataclass(frozen=True, slots=True)
class RoleAttributes:
    name: str
    is_superuser: bool
    bypasses_rls: bool


async def _describe_current_role(engine: AsyncEngine) -> RoleAttributes:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT rolname, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
    return RoleAttributes(name=row[0], is_superuser=row[1], bypasses_rls=row[2])


async def check_application_role(engine: AsyncEngine | None = None) -> RoleAttributes:
    """Raises PreflightError if the role is a superuser or holds BYPASSRLS."""
    role = await _describe_current_role(engine if engine is not None else get_engine())

    if role.is_superuser or role.bypasses_rls:
        detail = "superuser" if role.is_superuser else "BYPASSRLS"
        msg = (
            f"The application connects as '{role.name}', which holds {detail}. "
            "Row-level security does not apply to such a role, so tenant "
            "isolation is completely inert. Point CAIRN_DATABASE_URL at the "
            "cairn_app role."
        )
        raise PreflightError(msg)

    return role


async def check_platform_role(engine: AsyncEngine | None = None) -> RoleAttributes:
    """Raises PreflightError if the role can't bypass RLS or act as superuser."""
    role = await _describe_current_role(engine if engine is not None else get_platform_engine())

    if not (role.is_superuser or role.bypasses_rls):
        msg = (
            f"The platform connection uses '{role.name}', which has neither "
            "BYPASSRLS nor superuser. Because every table is FORCE ROW LEVEL "
            "SECURITY, signup and login would silently return no rows rather "
            "than failing — presenting as 'no such user' for every account. "
            "Grant BYPASSRLS to this role."
        )
        raise PreflightError(msg)

    return role


async def run_preflight_checks() -> None:
    await check_application_role()
    await check_platform_role()
