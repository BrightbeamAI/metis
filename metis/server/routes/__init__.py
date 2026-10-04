"""The Metis server's API routes, one module per area."""
from . import agents, audit, capture, chat, connectors, fragments, inbox, status, workspaces

ROUTERS = [workspaces.router, inbox.router, capture.router, connectors.router, chat.router,
           fragments.router, agents.router, audit.router, status.router]

__all__ = ["ROUTERS"]
