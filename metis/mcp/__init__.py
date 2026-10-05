"""The Metis MCP server: governed tacit memory as tools for any MCP client.

Run ``metis mcp``, or ``uvx metis-memory mcp`` without an install. The tool logic lives in
``metis.mcp.tools`` and has no dependency on the MCP SDK; ``metis.mcp.schema`` documents what
each tool takes and returns, and the server wiring is in ``metis.mcp.server``.
"""
