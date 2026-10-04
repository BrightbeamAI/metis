"""The Metis server's API routes, one module per area."""
from . import agents, audit, capture, fragments, inbox, workspaces

ROUTERS = [workspaces.router, inbox.router, capture.router, fragments.router, agents.router,
           audit.router]

__all__ = ["ROUTERS"]
