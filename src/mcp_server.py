"""
MCP (Model Context Protocol) server that exposes employee data as TOOLS.

Why MCP?
    MCP is an open standard for connecting AI applications to tools and data.
    Instead of the agent importing database code directly, it talks to this
    server over a standard protocol (stdio here). The same server could be
    plugged into Claude Desktop, Cursor or any other MCP client unchanged.

Security
    Every tool requires `requester_id`. Our agent fills it from the logged-in
    session - NOT from what the user typed - and the database layer enforces
    access rules. Errors are returned as {"error": ...} instead of crashing.

Run standalone (for testing with the MCP Inspector):
    mcp dev src/mcp_server.py
"""
import sys
from pathlib import Path

# Allow "python src/mcp_server.py" as well as "python -m src.mcp_server"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from src import database as db  # noqa: E402

mcp = FastMCP("goaified-helpdesk-employee-data", log_level="WARNING")


def _safe(fn, requester_id: str, target_employee_id: str):
    try:
        target = target_employee_id or requester_id
        return {"data": fn(requester_id, target)}
    except db.AccessDenied as e:
        return {"error": "ACCESS_DENIED", "message": str(e)}
    except Exception as e:  # never leak stack traces / SQL to the client
        return {"error": "INTERNAL_ERROR", "message": f"Could not fetch data ({type(e).__name__})."}


@mcp.tool()
def get_employee_profile(requester_id: str, target_employee_id: str = "") -> dict:
    """Get an employee's profile (name, department, job title, manager, location, join date).
    target_employee_id defaults to the requester themselves."""
    return _safe(db.get_employee_profile, requester_id, target_employee_id)


@mcp.tool()
def get_leave_balance(requester_id: str, target_employee_id: str = "") -> dict:
    """Get remaining annual, sick and casual leave days for an employee."""
    return _safe(db.get_leave_balance, requester_id, target_employee_id)


@mcp.tool()
def get_it_assets(requester_id: str, target_employee_id: str = "") -> dict:
    """List IT assets (laptop, monitor, ...) assigned to an employee."""
    return _safe(db.get_it_assets, requester_id, target_employee_id)


@mcp.tool()
def get_it_tickets(requester_id: str, target_employee_id: str = "") -> dict:
    """List IT service-desk tickets raised by an employee and their status."""
    return _safe(db.get_it_tickets, requester_id, target_employee_id)


if __name__ == "__main__":
    mcp.run()  # stdio transport
