from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pyodbc


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
        raise ValueError("Only fixed SELECT statements are allowed.")
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


def placeholders(values: list[Any]) -> str:
    if not values:
        raise ValueError("Expected at least one value.")
    return ",".join("?" for _ in values)


def export_optional(
    cursor: pyodbc.Cursor,
    out_dir: Path,
    file_name: str,
    table: str,
    sql: str,
    params: tuple[Any, ...],
) -> int:
    if not table_exists(cursor, table):
        return write_csv(out_dir / file_name, ["table_name", "note"], [[table, "table not found"]])
    return export_query(cursor, out_dir, file_name, sql, params)


def get_order_products(cursor: pyodbc.Cursor, order_number: int) -> list[str]:
    if not table_exists(cursor, "ord_log"):
        return []
    cursor.execute(
        """
        SELECT DISTINCT LTRIM(RTRIM(PROD_CD))
        FROM dbo.ord_log
        WHERE ORD_NUM = ?
          AND NULLIF(LTRIM(RTRIM(PROD_CD)), '') IS NOT NULL
        """,
        order_number,
    )
    return [str(row[0]) for row in cursor.fetchall()]


def get_order_customer(cursor: pyodbc.Cursor, order_number: int) -> str | None:
    if not table_exists(cursor, "orders"):
        return None
    cursor.execute(
        """
        SELECT TOP 1 LTRIM(RTRIM(CUS_ID))
        FROM dbo.orders
        WHERE ORD_NUM = ?
        """,
        order_number,
    )
    row = cursor.fetchone()
    return str(row[0]) if row and row[0] is not None else None


def capture(args: argparse.Namespace) -> Path:
    if not args.confirm_production_read:
        raise SystemExit("Refusing to connect without --confirm-production-read.")
    if not all(ch.isalnum() or ch in {"_", "-"} for ch in args.database):
        raise SystemExit("Database name contains unsupported characters.")

    products = [item.strip().upper() for item in args.product if item.strip()]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) / f"{stamp}_order_{args.order_number}"
    out_dir.mkdir(parents=True, exist_ok=True)

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

        inferred_customer = get_order_customer(cursor, args.order_number)
        customer_id = args.customer_id or inferred_customer

        inferred_products = get_order_products(cursor, args.order_number)
        for product in inferred_products:
            if product.upper() not in products:
                products.append(product.upper())

        exported: dict[str, int] = {}
        exported["server_info.csv"] = export_query(
            cursor,
            out_dir,
            "server_info.csv",
            """
            SELECT
                @@SERVERNAME AS server_name,
                DB_NAME() AS database_name,
                GETDATE() AS captured_at,
                SYSTEM_USER AS login_name,
                CURRENT_USER AS database_user_name
            """,
        )
        exported["order_header.csv"] = export_query(
            cursor,
            out_dir,
            "order_header.csv",
            "SELECT * FROM dbo.orders WHERE ORD_NUM = ?",
            (args.order_number,),
        )
        exported["order_lines.csv"] = export_query(
            cursor,
            out_dir,
            "order_lines.csv",
            "SELECT * FROM dbo.ord_log WHERE ORD_NUM = ? ORDER BY NT_NUM, Id",
            (args.order_number,),
        )
        exported["order_divisions.csv"] = export_optional(
            cursor,
            out_dir,
            "order_divisions.csv",
            "so_divs",
            "SELECT * FROM dbo.so_divs WHERE ORD_NUM = ? ORDER BY TYPE_CD, Id",
            (args.order_number,),
        )
        exported["order_extension_order2e.csv"] = export_optional(
            cursor,
            out_dir,
            "order_extension_order2e.csv",
            "order2e",
            "SELECT * FROM dbo.order2e WHERE ORD_NUM = ? ORDER BY ORD_NUM",
            (args.order_number,),
        )
        exported["order_extension_order2.csv"] = export_optional(
            cursor,
            out_dir,
            "order_extension_order2.csv",
            "order2",
            "SELECT * FROM dbo.order2 WHERE ORD_NUM = ? ORDER BY ORD_NUM",
            (args.order_number,),
        )
        exported["order_notes_olgdesc.csv"] = export_optional(
            cursor,
            out_dir,
            "order_notes_olgdesc.csv",
            "olgdesc",
            "SELECT * FROM dbo.olgdesc WHERE ORD_NUM = ? ORDER BY NT_NUM, TYPE_CD",
            (args.order_number,),
        )
        exported["order_bin_allocations.csv"] = export_optional(
            cursor,
            out_dir,
            "order_bin_allocations.csv",
            "bin_ord",
            "SELECT * FROM dbo.bin_ord WHERE ORD_NUM = ? ORDER BY NT_NUM, PROD_CD, WHS_NUM, BIN_CD",
            (args.order_number,),
        )
        exported["order_inventory_log.csv"] = export_optional(
            cursor,
            out_dir,
            "order_inventory_log.csv",
            "invt_log",
            "SELECT * FROM dbo.invt_log WHERE ORD_NUM = ? ORDER BY NT_NUM, Id",
            (args.order_number,),
        )

        if products:
            ph = placeholders(products)
            exported["products_inv.csv"] = export_optional(
                cursor,
                out_dir,
                "products_inv.csv",
                "inv",
                f"SELECT * FROM dbo.inv WHERE LTRIM(RTRIM(PROD_CD)) IN ({ph}) ORDER BY PROD_CD",
                tuple(products),
            )
            exported["products_inventory_inv_data.csv"] = export_optional(
                cursor,
                out_dir,
                "products_inventory_inv_data.csv",
                "inv_data",
                f"SELECT * FROM dbo.inv_data WHERE LTRIM(RTRIM(PROD_CD)) IN ({ph}) ORDER BY PROD_CD, WHS_NUM",
                tuple(products),
            )
            exported["products_bin_file.csv"] = export_optional(
                cursor,
                out_dir,
                "products_bin_file.csv",
                "bin_file",
                f"SELECT * FROM dbo.bin_file WHERE LTRIM(RTRIM(PROD_CD)) IN ({ph}) ORDER BY PROD_CD, WHS_NUM, BIN_CD",
                tuple(products),
            )
            exported["products_upc.csv"] = export_optional(
                cursor,
                out_dir,
                "products_upc.csv",
                "inv_upc",
                f"SELECT * FROM dbo.inv_upc WHERE LTRIM(RTRIM(PROD_CD)) IN ({ph}) ORDER BY PROD_CD",
                tuple(products),
            )
            exported["products_descriptions.csv"] = export_optional(
                cursor,
                out_dir,
                "products_descriptions.csv",
                "proddesc",
                f"SELECT * FROM dbo.proddesc WHERE LTRIM(RTRIM(PROD_CD)) IN ({ph}) ORDER BY PROD_CD",
                tuple(products),
            )

        if customer_id:
            exported["customer_master.csv"] = export_optional(
                cursor,
                out_dir,
                "customer_master.csv",
                "customer",
                "SELECT * FROM dbo.customer WHERE LTRIM(RTRIM(CUS_ID)) = ?",
                (customer_id,),
            )
            exported["customer_recent_orders.csv"] = export_optional(
                cursor,
                out_dir,
                "customer_recent_orders.csv",
                "orders",
                """
                SELECT TOP 50 *
                FROM dbo.orders
                WHERE LTRIM(RTRIM(CUS_ID)) = ?
                ORDER BY ORD_NUM DESC
                """,
                (customer_id,),
            )
            exported["customer_chain_stores.csv"] = export_optional(
                cursor,
                out_dir,
                "customer_chain_stores.csv",
                "chn_str",
                "SELECT * FROM dbo.chn_str WHERE LTRIM(RTRIM(CUS_ID)) = ? ORDER BY STR_NUM",
                (customer_id,),
            )
            exported["customer_divisions.csv"] = export_optional(
                cursor,
                out_dir,
                "customer_divisions.csv",
                "cus_divs",
                "SELECT * FROM dbo.cus_divs WHERE LTRIM(RTRIM(CUS_ID)) = ?",
                (customer_id,),
            )
            exported["customer_notes.csv"] = export_optional(
                cursor,
                out_dir,
                "customer_notes.csv",
                "cusnt",
                "SELECT * FROM dbo.cusnt WHERE LTRIM(RTRIM(CUS_ID)) = ?",
                (customer_id,),
            )
            if products:
                ph = placeholders(products)
                exported["customer_product_history_cus_invt.csv"] = export_optional(
                    cursor,
                    out_dir,
                    "customer_product_history_cus_invt.csv",
                    "cus_invt",
                    f"""
                    SELECT *
                    FROM dbo.cus_invt
                    WHERE LTRIM(RTRIM(CUS_ID)) = ?
                      AND LTRIM(RTRIM(PROD_CD)) IN ({ph})
                    ORDER BY PROD_CD
                    """,
                    tuple([customer_id] + products),
                )
                exported["customer_product_prices_cust_inv.csv"] = export_optional(
                    cursor,
                    out_dir,
                    "customer_product_prices_cust_inv.csv",
                    "cust_inv",
                    f"""
                    SELECT *
                    FROM dbo.cust_inv
                    WHERE LTRIM(RTRIM(CUS_ID)) = ?
                      AND LTRIM(RTRIM(PROD_CD)) IN ({ph})
                    ORDER BY PROD_CD
                    """,
                    tuple([customer_id] + products),
                )

        manifest = {
            "order_number": args.order_number,
            "customer_id": customer_id,
            "inferred_customer_id": inferred_customer,
            "products": products,
            "inferred_products": inferred_products,
            "dsn": args.dsn,
            "database": args.database,
            "captured_at_local": datetime.now().isoformat(timespec="seconds"),
            "output_dir": str(out_dir),
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
    parser = argparse.ArgumentParser(description="Capture a read-only OMS order context.")
    parser.add_argument("--dsn", default="test", help="ODBC DSN name. Default: test")
    parser.add_argument("--database", default="omsdata", help="OMS database name. Default: omsdata")
    parser.add_argument("--order-number", type=int, required=True, help="Sales order number to capture.")
    parser.add_argument("--customer-id", default="", help="Optional customer id. If omitted, inferred from orders.")
    parser.add_argument("--product", action="append", default=[], help="Product code to capture. Can be repeated.")
    parser.add_argument("--out-dir", default="order_context", help="Output directory relative to this script folder.")
    parser.add_argument("--timeout", type=int, default=15, help="ODBC connection timeout seconds.")
    parser.add_argument("--confirm-production-read", action="store_true", help="Required safety flag.")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    args.out_dir = str((script_dir / args.out_dir).resolve())
    out_dir = capture(args)
    print(f"Order context written to: {out_dir}")


if __name__ == "__main__":
    main()
