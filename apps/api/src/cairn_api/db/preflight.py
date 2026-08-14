"""Startup checks that verify isolation is actually in force.

Every control this system relies on can be silently disabled by configuration
rather than by code:

- Point ``CAIRN_DATABASE_URL`` at a superuser and **every row-level security
  policy becomes inert**, while ``pg_policies`` stays populated,
  ``relforcerowsecurity`` stays true, and the test suite stays green. This
  project already shipped exactly that state once.
- Point ``CAIRN_PLATFORM_DATABASE_URL`` at a role without ``BYPASSRLS`` and,
  because every table is ``FORCE``d, signup and login return nothing at all —
  a total outage that looks like "no such user".

Neither failure raises. Both look healthy from the outside. So the properties
are asserted at boot, against the live connections, and the process refuses to
start if they do not hold.

One query each. The cost is negligible; the class of bug it closes is not.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cairn_api.db.session import get_engine, get_platform_engine


class PreflightError(RuntimeError):
    """A required database property is not in force. The process must not start."""


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
    """The application connection must be subject to row-level security.

    Args:
        engine: Override, so the failure path can be exercised against a role
            deliberately created with the wrong attributes. A check whose
            failure branch is never executed is decoration.

    Raises:
        PreflightError: If the role is a superuser or holds BYPASSRLS, either of
            which silently disables tenant isolation entirely.
    """
    role = await _describe_current_role(engine if engine is not None else get_engine())

    if role.is_superuser or role.bypasses_rls:
        detail = "superuser" if role.is_superuser else "BYPASSRLS"
        msg = (
            f"The application connects as '{role.name}', which holds {detail}. "
            "Row-level security does not apply to such a role, so tenant "
            "isolation is completely inert — every policy would be bypassed "
            "while all monitoring reports healthy. Point CAIRN_DATABASE_URL at "
            "the cairn_app role."
        )
        raise PreflightError(msg)

    return role


async def check_platform_role(engine: AsyncEngine | None = None) -> RoleAttributes:
    """The platform connection must be able to bypass row-level security.

    Signup, login and invitation acceptance all run before a tenant is known, so
    they cannot be scoped. Because every table is ``FORCE``d, a platform role
    without ``BYPASSRLS`` reads nothing — and the symptom is not an error but an
    apparently empty database.

    Raises:
        PreflightError: If the role can neither bypass RLS nor act as superuser.
    """
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
    """Verify database isolation properties. Call before serving traffic.

    Deliberately fails the process rather than logging a warning. A warning
    about disabled tenant isolation is a warning nobody reads until after the
    incident.
    """
    await check_application_role()
    await check_platform_role()
