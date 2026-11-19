"""
PostgreSQL layer: schema, synthetic seed data, authentication and
ACCESS-CONTROLLED queries.

Key security idea (good to explain in an interview):
    The LLM never decides who may see what. Every data function takes the
    *authenticated* requester_id (from the login session, not from the chat
    text) and checks permissions in Python BEFORE running the query.
    So even a perfect prompt-injection cannot make the database return
    another employee's record.

Access rules
    - employee  : can see only their own records
    - manager   : own records + basic records of their direct reports
    - hr_admin  : everyone's records
    Sensitive fields (salary band, personal phone) are visible only to the
    employee themselves and hr_admin - never to managers.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import date

import psycopg
from psycopg.rows import dict_row

from src import config

# --------------------------------------------------------------- connection
@contextmanager
def get_conn():
    conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def hash_pin(pin: str) -> str:
    # Demo-grade hashing. In production use bcrypt/argon2 + SSO (e.g. Azure AD).
    return hashlib.sha256(f"goaified-salt::{pin}".encode()).hexdigest()


# ------------------------------------------------------------------- schema
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS employees (
    employee_id     VARCHAR(10) PRIMARY KEY,
    full_name       VARCHAR(100) NOT NULL,
    work_email      VARCHAR(120) UNIQUE NOT NULL,
    personal_phone  VARCHAR(20),
    department      VARCHAR(50) NOT NULL,
    job_title       VARCHAR(80) NOT NULL,
    role            VARCHAR(20) NOT NULL CHECK (role IN ('employee','manager','hr_admin')),
    manager_id      VARCHAR(10) REFERENCES employees(employee_id),
    location        VARCHAR(50),
    join_date       DATE NOT NULL,
    salary_band     VARCHAR(5),
    pin_hash        VARCHAR(64) NOT NULL
);

CREATE TABLE IF NOT EXISTS leave_balances (
    employee_id  VARCHAR(10) PRIMARY KEY REFERENCES employees(employee_id),
    annual_left  NUMERIC(4,1) NOT NULL,
    sick_left    NUMERIC(4,1) NOT NULL,
    casual_left  NUMERIC(4,1) NOT NULL,
    updated_on   DATE NOT NULL DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS it_assets (
    asset_tag    VARCHAR(20) PRIMARY KEY,
    employee_id  VARCHAR(10) REFERENCES employees(employee_id),
    asset_type   VARCHAR(30) NOT NULL,
    model        VARCHAR(80) NOT NULL,
    assigned_on  DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS it_tickets (
    ticket_id    VARCHAR(20) PRIMARY KEY,
    employee_id  VARCHAR(10) REFERENCES employees(employee_id),
    title        VARCHAR(200) NOT NULL,
    status       VARCHAR(20) NOT NULL CHECK (status IN ('Open','In Progress','Resolved','Closed')),
    created_on   DATE NOT NULL
);

-- Every data access attempt (allowed or denied) is recorded for auditing
CREATE TABLE IF NOT EXISTS access_log (
    id            SERIAL PRIMARY KEY,
    requester_id  VARCHAR(10),
    target_id     VARCHAR(10),
    action        VARCHAR(50),
    allowed       BOOLEAN,
    logged_at     TIMESTAMP DEFAULT NOW()
);
"""

# Synthetic data only - no real people.
EMPLOYEES = [
    # id, name, email, phone, dept, title, role, manager, location, join, band, pin
    ("E1006", "Kavya Reddy", "kavya.reddy@goaified.example", "+91 98480 11006", "Human Resources", "HR Manager", "hr_admin", None, "Hyderabad", date(2019, 4, 1), "B4", "6666"),
    ("E1004", "Arjun Mehta", "arjun.mehta@goaified.example", "+91 98480 11004", "Analytics", "Analytics Manager", "manager", None, "Hyderabad", date(2020, 7, 15), "B4", "4444"),
    ("E1005", "Sneha Kapoor", "sneha.kapoor@goaified.example", "+91 98480 11005", "Engineering", "Engineering Manager", "manager", None, "Bengaluru", date(2018, 11, 5), "B5", "5555"),
    ("E1001", "Priya Sharma", "priya.sharma@goaified.example", "+91 98480 11001", "Analytics", "Data Analyst", "employee", "E1004", "Hyderabad", date(2023, 2, 1), "B2", "1111"),
    ("E1002", "Rahul Verma", "rahul.verma@goaified.example", "+91 98480 11002", "Engineering", "Software Engineer", "employee", "E1005", "Bengaluru", date(2022, 6, 20), "B2", "2222"),
    ("E1003", "Vikram Rao", "vikram.rao@goaified.example", "+91 98480 11003", "Engineering", "DevOps Engineer", "employee", "E1005", "Pune", date(2024, 1, 10), "B3", "3333"),
    ("E1007", "Meera Nair", "meera.nair@goaified.example", "+91 98480 11007", "Analytics", "Data Scientist", "employee", "E1004", "Remote", date(2025, 9, 1), "B3", "7777"),
]

LEAVES = [
    ("E1001", 12.5, 8, 4), ("E1002", 6, 10, 2), ("E1003", 15, 7, 5),
    ("E1004", 9, 9, 3), ("E1005", 18, 10, 6), ("E1006", 11, 6, 4), ("E1007", 4.5, 10, 6),
]

ASSETS = [
    ("LAP-2301", "E1001", "Laptop", "Dell Precision 5680 (32 GB RAM)", date(2023, 2, 1)),
    ("MON-1104", "E1001", "Monitor", "Dell UltraSharp 27\"", date(2023, 3, 10)),
    ("LAP-2215", "E1002", "Laptop", "MacBook Pro 14\" M3 (32 GB RAM)", date(2022, 6, 20)),
    ("LAP-2402", "E1003", "Laptop", "Dell Precision 5680 (32 GB RAM)", date(2024, 1, 10)),
    ("LAP-2007", "E1004", "Laptop", "MacBook Pro 16\" (32 GB RAM)", date(2020, 7, 15)),
    ("LAP-1811", "E1005", "Laptop", "Dell Latitude 7440 (16 GB RAM)", date(2022, 11, 5)),
    ("LAP-1904", "E1006", "Laptop", "MacBook Air 13\" (16 GB RAM)", date(2023, 4, 1)),
    ("LAP-2509", "E1007", "Laptop", "Dell Precision 5690 (32 GB RAM)", date(2025, 9, 1)),
]

TICKETS = [
    ("INC-10231", "E1001", "VPN disconnects every 10 minutes", "In Progress", date(2026, 11, 12)),
    ("REQ-10244", "E1001", "Software request: Tableau Desktop licence", "Open", date(2026, 11, 15)),
    ("INC-10198", "E1002", "Laptop battery draining fast", "Resolved", date(2026, 10, 28)),
    ("REQ-10250", "E1003", "Temporary admin rights for Docker install", "Open", date(2026, 11, 17)),
    ("INC-10210", "E1007", "MFA not working after phone change", "Closed", date(2026, 11, 3)),
]


def init_db(reset: bool = False) -> None:
    """Create tables and load synthetic data."""
    with get_conn() as conn:
        if reset:
            conn.execute(
                "DROP TABLE IF EXISTS access_log, it_tickets, it_assets, leave_balances, employees CASCADE"
            )
        conn.execute(SCHEMA_SQL)
        with conn.cursor() as cur:
            for e in EMPLOYEES:
                cur.execute(
                    """INSERT INTO employees VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (employee_id) DO NOTHING""",
                    (*e[:11], hash_pin(e[11])),
                )
            cur.executemany(
                "INSERT INTO leave_balances (employee_id, annual_left, sick_left, casual_left) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                LEAVES,
            )
            cur.executemany("INSERT INTO it_assets VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", ASSETS)
            cur.executemany("INSERT INTO it_tickets VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", TICKETS)


# ------------------------------------------------------------ authentication
def authenticate(employee_id: str, pin: str) -> dict | None:
    """Return basic identity if the ID + PIN are correct, otherwise None."""
    employee_id = (employee_id or "").strip().upper()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT employee_id, full_name, role, department, job_title FROM employees "
            "WHERE employee_id = %s AND pin_hash = %s",
            (employee_id, hash_pin(pin or "")),
        ).fetchone()
    return row


# ------------------------------------------------------------- authorization
class AccessDenied(Exception):
    pass


def _get_role_and_manager(conn, employee_id: str) -> dict | None:
    return conn.execute(
        "SELECT employee_id, role, manager_id FROM employees WHERE employee_id = %s", (employee_id,)
    ).fetchone()


def check_access(conn, requester_id: str, target_id: str, action: str, sensitive: bool = False) -> None:
    """Raise AccessDenied unless requester may perform `action` on target. Always logs."""
    requester = _get_role_and_manager(conn, requester_id)
    target = _get_role_and_manager(conn, target_id)

    allowed = False
    if requester and target:
        if requester_id == target_id or requester["role"] == "hr_admin":
            allowed = True
        elif requester["role"] == "manager" and target["manager_id"] == requester_id and not sensitive:
            allowed = True

    conn.execute(
        "INSERT INTO access_log (requester_id, target_id, action, allowed) VALUES (%s,%s,%s,%s)",
        (requester_id, target_id, action, allowed),
    )
    conn.commit()  # keep the audit record even if we raise below
    if not target and requester:
        raise AccessDenied(f"Employee {target_id} was not found.")
    if not allowed:
        raise AccessDenied(
            "You are not authorised to view this employee's information. "
            "Employees can only view their own records."
        )


def _clean(row: dict | None) -> dict | None:
    """Convert dates/decimals to JSON-friendly types."""
    if row is None:
        return None
    return {k: (v.isoformat() if isinstance(v, date) else float(v) if hasattr(v, "as_tuple") else v)
            for k, v in row.items()}


# --------------------------------------------------------------- data access
def get_employee_profile(requester_id: str, target_id: str) -> dict:
    target_id = target_id.strip().upper()
    with get_conn() as conn:
        requester = _get_role_and_manager(conn, requester_id)
        can_see_sensitive = requester is not None and (
            requester_id == target_id or requester["role"] == "hr_admin"
        )
        check_access(conn, requester_id, target_id, "get_employee_profile")
        row = conn.execute(
            """SELECT e.employee_id, e.full_name, e.work_email, e.department, e.job_title,
                      e.location, e.join_date, m.full_name AS manager_name,
                      e.salary_band, e.personal_phone
               FROM employees e LEFT JOIN employees m ON e.manager_id = m.employee_id
               WHERE e.employee_id = %s""",
            (target_id,),
        ).fetchone()
    row = _clean(row)
    if not can_see_sensitive:
        row.pop("salary_band", None)
        row.pop("personal_phone", None)
    return row


def get_leave_balance(requester_id: str, target_id: str) -> dict:
    target_id = target_id.strip().upper()
    with get_conn() as conn:
        check_access(conn, requester_id, target_id, "get_leave_balance")
        row = conn.execute(
            "SELECT employee_id, annual_left, sick_left, casual_left, updated_on "
            "FROM leave_balances WHERE employee_id = %s",
            (target_id,),
        ).fetchone()
    return _clean(row) or {}


def get_it_assets(requester_id: str, target_id: str) -> list[dict]:
    target_id = target_id.strip().upper()
    with get_conn() as conn:
        check_access(conn, requester_id, target_id, "get_it_assets")
        rows = conn.execute(
            "SELECT asset_tag, asset_type, model, assigned_on FROM it_assets "
            "WHERE employee_id = %s ORDER BY assigned_on",
            (target_id,),
        ).fetchall()
    return [_clean(r) for r in rows]


def get_it_tickets(requester_id: str, target_id: str) -> list[dict]:
    target_id = target_id.strip().upper()
    with get_conn() as conn:
        check_access(conn, requester_id, target_id, "get_it_tickets")
        rows = conn.execute(
            "SELECT ticket_id, title, status, created_on FROM it_tickets "
            "WHERE employee_id = %s ORDER BY created_on DESC",
            (target_id,),
        ).fetchall()
    return [_clean(r) for r in rows]


def get_recent_access_log(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT requester_id, target_id, action, allowed, logged_at FROM access_log "
            "ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    return [{**r, "logged_at": r["logged_at"].strftime("%Y-%m-%d %H:%M:%S")} for r in rows]
