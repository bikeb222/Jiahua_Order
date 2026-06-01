from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pyodbc


CORE_TABLES = [
    "orders",
    "ord_log",
    "so_divs",
    "order2e",
    "order2",
    "inv_data",
    "bin_file",
    "bin_ord",
    "invoice",
    "ins_data",
    "ins_divs",
    "invt_log",
    "olgdesc",
    "pay_log",
    "pay_auth",
    "customer",
]


def clean_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def write_csv(path: Path, columns: list[str], rows: Iterable[Iterable[Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([clean_value(value) for value in row])
            count += 1
    return count


def fetch_all(cursor: pyodbc.Cursor, sql: str, params: tuple[Any, ...] = ()) -> tuple[list[str], list[tuple[Any, ...]]]:
    if not sql.lstrip().upper().startswith("SELECT"):
        raise ValueError("Snapshot tool only allows SELECT statements.")
    cursor.execute(sql, params)
    columns = [column[0] for column in cursor.description or []]
    return columns, [tuple(row) for row in cursor.fetchall()]


def export_query(
    cursor: pyodbc.Cursor,
    out_dir: Path,
    file_name: str,
    sql: str,
    params: tuple[Any, ...] = (),
) -> int:
    columns, rows = fetch_all(cursor, sql, params)
    return write_csv(out_dir / file_name, columns, rows)


def table_exists(cursor: pyodbc.Cursor, table: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME = ?
        """,
        table,
    )
    return int(cursor.fetchone()[0]) > 0


def export_light_metrics(cursor: pyodbc.Cursor, out_dir: Path) -> int:
    return export_query(
        cursor,
        out_dir,
        "light_metrics.csv",
        """
        SELECT
            (SELECT MAX(ORD_NUM) FROM dbo.orders WHERE ORD_NUM > 0 AND ORD_NUM < 500000) AS max_order_number,
            (SELECT MAX(INVS_NUM) FROM dbo.invoice) AS max_invoice_number,
            (SELECT COUNT(*) FROM dbo.inv_data) AS inv_data_rows,
            (SELECT COUNT(*) FROM dbo.bin_file) AS bin_file_rows,
            (SELECT COUNT(*) FROM dbo.orders WHERE ORD_NUM > 0 AND ORD_NUM < 500000) AS sales_order_rows
        """,
    )


def export_recent_order_related(
    cursor: pyodbc.Cursor,
    out_dir: Path,
    recent_orders: int,
    include_heavy_related: bool,
) -> dict[str, int]:
    exported: dict[str, int] = {}
    exported["recent_orders.csv"] = export_query(
        cursor,
        out_dir,
        "recent_orders.csv",
        f"""
        SELECT TOP {recent_orders} *
        FROM dbo.orders
        WHERE ORD_NUM > 0
          AND ORD_NUM < 500000
        ORDER BY ORD_NUM DESC
        """,
    )

    cursor.execute(
        f"""
        SELECT TOP {recent_orders} ORD_NUM
        FROM dbo.orders
        WHERE ORD_NUM > 0
          AND ORD_NUM < 500000
        ORDER BY ORD_NUM DESC
        """
    )
    order_numbers = [int(row[0]) for row in cursor.fetchall()]
    if not order_numbers:
        return exported

    order_values = ",".join(str(num) for num in order_numbers)
    related_queries = {
        "recent_ord_log.csv": f"SELECT * FROM dbo.ord_log WHERE ORD_NUM IN ({order_values}) ORDER BY ORD_NUM DESC, NT_NUM, Id",
        "recent_so_divs.csv": f"SELECT * FROM dbo.so_divs WHERE ORD_NUM IN ({order_values}) ORDER BY ORD_NUM DESC, TYPE_CD, Id",
        "recent_order2e.csv": f"SELECT * FROM dbo.order2e WHERE ORD_NUM IN ({order_values}) ORDER BY ORD_NUM DESC",
        "recent_order2.csv": f"SELECT * FROM dbo.order2 WHERE ORD_NUM IN ({order_values}) ORDER BY ORD_NUM DESC",
    }
    if include_heavy_related:
        related_queries.update(
            {
                "recent_bin_ord.csv": f"SELECT * FROM dbo.bin_ord WHERE ORD_NUM IN ({order_values}) ORDER BY ORD_NUM DESC, NT_NUM",
                "recent_invt_log.csv": f"SELECT * FROM dbo.invt_log WHERE ORD_NUM IN ({order_values}) ORDER BY ORD_NUM DESC, NT_NUM, Id",
                "recent_olgdesc.csv": f"SELECT * FROM dbo.olgdesc WHERE ORD_NUM IN ({order_values}) ORDER BY ORD_NUM DESC, NT_NUM, TYPE_CD",
                "recent_pay_log.csv": f"SELECT * FROM dbo.pay_log WHERE ORD_NUM IN ({order_values}) ORDER BY ORD_NUM DESC, ID",
                "recent_pay_auth.csv": f"SELECT * FROM dbo.pay_auth WHERE ORD_NUM IN ({order_values}) ORDER BY ORD_NUM DESC, ID",
            }
        )
    for file_name, sql in related_queries.items():
        table = file_name.replace("recent_", "").replace(".csv", "")
        if table_exists(cursor, table):
            exported[file_name] = export_query(cursor, out_dir, file_name, sql)

    return exported


def capture(args: argparse.Namespace) -> Path:
    if not args.confirm_production_read:
        raise SystemExit(
            "Refusing to connect to the real database without --confirm-production-read. "
            "This is a read-only snapshot tool, but production access should be explicit."
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in args.label)
    out_dir = Path(args.out_dir) / f"{stamp}_{safe_label}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not all(ch.isalnum() or ch in {"_", "-"} for ch in args.database):
        raise SystemExit("Database name contains unsupported characters.")

    conn = pyodbc.connect(
        f"DSN={args.dsn};DATABASE={args.database};ApplicationIntent=ReadOnly;",
        autocommit=True,
        timeout=args.timeout,
    )
    try:
        cursor = conn.cursor()
        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;")
        cursor.execute("SELECT DB_NAME()")
        current_database = str(cursor.fetchone()[0])
        if current_database.lower() != args.database.lower():
            raise SystemExit(f"Connected to '{current_database}', expected '{args.database}'. Stopping.")
        if not table_exists(cursor, "orders"):
            raise SystemExit(f"Connected to '{current_database}', but dbo.orders was not found. Stopping.")

        exported: dict[str, int] = {}
        exported["server_info.csv"] = export_query(
            cursor,
            out_dir,
            "server_info.csv",
            """
            SELECT
                @@SERVERNAME AS server_name,
                DB_NAME() AS database_name,
                SYSTEM_USER AS login_name,
                CURRENT_USER AS database_user_name,
                GETDATE() AS captured_at,
                SERVERPROPERTY('Edition') AS edition,
                SERVERPROPERTY('ProductVersion') AS product_version
            """,
        )
        exported["table_counts.csv"] = export_query(
            cursor,
            out_dir,
            "table_counts.csv",
            """
            SELECT
                t.name AS table_name,
                SUM(p.rows) AS row_count
            FROM sys.tables AS t
            JOIN sys.partitions AS p
              ON p.object_id = t.object_id
             AND p.index_id IN (0, 1)
            WHERE t.name IN (
                'orders', 'ord_log', 'so_divs', 'order2e', 'order2',
                'inv_data', 'bin_file', 'bin_ord', 'invoice',
                'ins_data', 'ins_divs', 'invt_log', 'olgdesc',
                'pay_log', 'pay_auth', 'customer'
            )
            GROUP BY t.name
            ORDER BY t.name
            """,
        )
        exported["light_metrics.csv"] = export_light_metrics(cursor, out_dir)
        exported.update(
            export_recent_order_related(
                cursor,
                out_dir,
                args.recent_orders,
                args.include_heavy_related,
            )
        )
        exported["recent_invoices.csv"] = export_query(
            cursor,
            out_dir,
            "recent_invoices.csv",
            f"""
            SELECT TOP {args.recent_invoices} *
            FROM dbo.invoice
            ORDER BY INVS_NUM DESC
            """,
        )

        if not args.skip_full_inventory:
            exported["inv_data_full.csv"] = export_query(
                cursor,
                out_dir,
                "inv_data_full.csv",
                """
                SELECT *
                FROM dbo.inv_data
                ORDER BY PROD_CD, WHS_NUM
                """,
            )
            exported["bin_file_full.csv"] = export_query(
                cursor,
                out_dir,
                "bin_file_full.csv",
                """
                SELECT *
                FROM dbo.bin_file
                ORDER BY PROD_CD, WHS_NUM, BIN_CD
                """,
            )

        manifest = {
            "label": args.label,
            "captured_at_local": datetime.now().isoformat(timespec="seconds"),
            "dsn": args.dsn,
            "database": args.database,
            "output_dir": str(out_dir),
            "recent_orders": args.recent_orders,
            "recent_invoices": args.recent_invoices,
            "skip_full_inventory": args.skip_full_inventory,
            "include_heavy_related": args.include_heavy_related,
            "exported_files": exported,
            "safety": {
                "sql_mode": "fixed SELECT statements only",
                "autocommit": True,
                "isolation": "READ UNCOMMITTED",
                "application_intent": "ReadOnly",
                "writes": False,
            },
        }
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return out_dir
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture a read-only OMS production snapshot.")
    parser.add_argument("--dsn", default="test", help="ODBC DSN name. Default: test")
    parser.add_argument("--database", default="omsdata", help="OMS database name. Default: omsdata")
    parser.add_argument("--label", default="before", help="Label added to the snapshot folder name.")
    parser.add_argument("--out-dir", default="snapshots", help="Output directory relative to this script folder.")
    parser.add_argument("--recent-orders", type=int, default=200, help="How many latest sales orders to export.")
    parser.add_argument("--recent-invoices", type=int, default=200, help="How many latest invoices to export.")
    parser.add_argument("--timeout", type=int, default=15, help="ODBC connection timeout seconds.")
    parser.add_argument("--skip-full-inventory", action="store_true", help="Skip full inv_data/bin_file export.")
    parser.add_argument(
        "--include-heavy-related",
        action="store_true",
        help="Also query heavier related tables such as invt_log/pay_log/bin_ord for recent orders.",
    )
    parser.add_argument("--confirm-production-read", action="store_true", help="Required safety flag.")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    args.out_dir = str((script_dir / args.out_dir).resolve())
    out_dir = capture(args)
    print(f"Snapshot written to: {out_dir}")


if __name__ == "__main__":
    main()
