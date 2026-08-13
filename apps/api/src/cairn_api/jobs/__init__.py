"""Background job infrastructure.

CAIRN is almost entirely background work, so this package carries the tenant
isolation guarantee for the majority of the system. See ``runner.py`` for the
structural rule: a handler never opens its own session.
"""

from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.runner import (
    JobHandler,
    JobRegistry,
    UnknownJobTypeError,
    registry,
    run_job,
)

__all__ = [
    "JobEnvelope",
    "JobHandler",
    "JobRegistry",
    "UnknownJobTypeError",
    "registry",
    "run_job",
]
