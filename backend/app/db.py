from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

import pyodbc
from dotenv import load_dotenv


load_dotenv()


DEFAULT_CONNECTION_STRING = (
    "Driver={ODBC Driver 18 for SQL Server};"
    "Server=.\\OMSDEV;"
    "Database=omsdata_local;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)

BLOCKED_SERVER_PARTS = ("SRV2019", "UPSWS2022SERVER")
LOCAL_DATABASE_NAME = "omsdata_local"
PRODUCTION_DATABASE_NAME = "omsdata"
APP_WRITE_ENV = "ORDER_ENABLE_APP_WRITE"
PRODUCTION_READ_ENV = "ORDER_ALLOW_PRODUCTION_READ"
PRODUCTION_WRITE_ENV = "ORDER_ENABLE_PRODUCTION_OMS_WRITE"
PRODUCTION_WRITE_ACK_ENV = "ORDER_PRODUCTION_WRITE_ACK"
PRODUCTION_WRITE_ACK = "I_UNDERSTAND_THIS_WRITES_TO_PRODUCTION_OMS"
DB_LOCK_TIMEOUT_MS = int(os.getenv("ORDER_DB_LOCK_TIMEOUT_MS", "5000"))
DB_QUERY_TIMEOUT_SECONDS = int(os.getenv("ORDER_DB_QUERY_TIMEOUT_SECONDS", "15"))


def get_read_connection_string() -> str:
    return os.getenv("ORDER_READ_DB_CONNECTION") or os.getenv("ORDER_DB_CONNECTION", DEFAULT_CONNECTION_STRING)


def get_write_connection_string() -> str:
    return os.getenv("ORDER_WRITE_DB_CONNECTION") or os.getenv("ORDER_DB_CONNECTION", DEFAULT_CONNECTION_STRING)


@contextmanager
def connect(write: bool = False):
    conn = pyodbc.connect(
        get_write_connection_string() if write else get_read_connection_string(),
        autocommit=False,
        timeout=8,
    )
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def rows_to_dicts(cursor: pyodbc.Cursor) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description or []]
    return [
        {columns[index]: normalize_value(value) for index, value in enumerate(row)}
        for row in cursor.fetchall()
    ]


def query(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    sql_text = sql.strip().lower()
    if not (sql_text.startswith("select") or sql_text.startswith("with")):
        raise ValueError("Only SELECT queries are allowed in the backend database helper.")

    with connect() as conn:
        conn.timeout = DB_QUERY_TIMEOUT_SECONDS
        cursor = conn.cursor()
        cursor.execute(f"SET LOCK_TIMEOUT {DB_LOCK_TIMEOUT_MS};")
        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;")
        cursor.execute(sql, tuple(params))
        return rows_to_dicts(cursor)


def query_one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def app_write_enabled() -> bool:
    return os.getenv(APP_WRITE_ENV, "").lower() in {"1", "true", "yes"}


def production_write_enabled() -> bool:
    return (
        os.getenv(PRODUCTION_WRITE_ENV, "").lower() in {"1", "true", "yes"}
        and os.getenv(PRODUCTION_WRITE_ACK_ENV, "") == PRODUCTION_WRITE_ACK
    )


def require_app_write_enabled(database_name: str | None = None) -> None:
    if not app_write_enabled():
        raise RuntimeError(
            f"App write is disabled. Set {APP_WRITE_ENV}=true only for local development tests."
        )
    if database_name == PRODUCTION_DATABASE_NAME and not production_write_enabled():
        raise RuntimeError(
            "Production OMS write is disabled. Keep this off until the OMS write plan has been "
            "field-verified against the legacy software."
        )


def _connection_info(write: bool = False) -> dict[str, Any]:
    with connect(write=write) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                @@SERVERNAME AS server_name,
                DB_NAME() AS database_name,
                SERVERPROPERTY('Edition') AS edition,
                SERVERPROPERTY('ProductVersion') AS product_version
            """
        )
        rows = rows_to_dicts(cursor)
    if not rows:
        raise RuntimeError("Could not read SQL Server connection information.")
    return rows[0]


def assert_safe_database(write: bool = False) -> dict[str, Any]:
    info = _connection_info(write=write)
    server_name = str(info["server_name"]).upper()
    database_name = str(info["database_name"])
    allow_non_local = os.getenv("ORDER_ALLOW_NON_LOCAL_DB", "").lower() in {"1", "true", "yes"}
    allow_production_read = os.getenv(PRODUCTION_READ_ENV, "").lower() in {"1", "true", "yes"}

    if database_name == LOCAL_DATABASE_NAME:
        return info

    if database_name == PRODUCTION_DATABASE_NAME:
        if write:
            if any(part in server_name for part in BLOCKED_SERVER_PARTS) and not production_write_enabled():
                raise RuntimeError(
                    f"Refusing production write against SQL Server instance: {info['server_name']}"
                )
            require_app_write_enabled(database_name)
            return info
        if allow_production_read:
            return info
        raise RuntimeError(
            f"Refusing to read production database '{database_name}' unless {PRODUCTION_READ_ENV}=true."
        )

    if any(part in server_name for part in BLOCKED_SERVER_PARTS):
        raise RuntimeError(f"Refusing to start against blocked SQL Server instance: {info['server_name']}")

    if not allow_non_local:
        raise RuntimeError(
            f"Refusing to start against database '{database_name}'. "
            f"Expected '{LOCAL_DATABASE_NAME}' or explicit production-read configuration."
        )

    return info


@contextmanager
def write_transaction():
    info = assert_safe_database(write=True)
    require_app_write_enabled(str(info["database_name"]))
    conn = pyodbc.connect(get_write_connection_string(), autocommit=True, timeout=8)
    conn.timeout = DB_QUERY_TIMEOUT_SECONDS
    cursor = conn.cursor()
    try:
        cursor.execute("SET XACT_ABORT ON;")
        cursor.execute(f"SET LOCK_TIMEOUT {DB_LOCK_TIMEOUT_MS};")
        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED;")
        cursor.execute("BEGIN TRANSACTION;")
        yield conn
        cursor.execute("COMMIT TRANSACTION;")
    except Exception:
        try:
            cursor.execute("IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def insert_and_get_id(cursor: pyodbc.Cursor, sql: str, params: Iterable[Any]) -> int:
    cursor.execute(sql + "; SELECT CONVERT(int, SCOPE_IDENTITY()) AS id;", tuple(params))
    while cursor.description is None:
        if not cursor.nextset():
            raise RuntimeError("Insert did not return an identity value.")
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Insert did not return an identity value.")
    return int(row[0])
