"""HTTP layer.

The transport. Everything here translates between HTTP and the domain services
in ``cairn_api.auth`` and below, and holds no business rules of its own — so the
domain stays testable without a request in the way, and a second transport
(a worker, a CLI) does not have to route through FastAPI to reuse it.
"""

from cairn_api.api.app import create_app

__all__ = ["create_app"]
