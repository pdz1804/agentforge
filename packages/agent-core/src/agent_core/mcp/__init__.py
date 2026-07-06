"""MCP connector — adapt external MCP-server tools into BaseTools."""

from .connector import StdioMCPConnector, build_mcp_tools

__all__ = ["StdioMCPConnector", "build_mcp_tools"]
