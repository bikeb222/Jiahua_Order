from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .db import app_write_enabled, assert_safe_database, insert_and_get_id, query, query_one, write_transaction
from .pdf_reports import invoice_pdf, picking_list_pdf
from .server_print import PrintError, print_pdf_bytes


app = FastAPI(
    title="OMS Order Entry API",
    description="Read-only helper API for rebuilding the legacy OMS Add Order workflow.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8008"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|192\.168\.\d+\.\d+):517[34]",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


SALES_USERS = [
    "TINA",
    "JUDY",
    "RAINNIE",
    "ISIDRO",
    "VON",
    "LINA",
    "WEI",
    "JASON",
    "RAMON",
    "JAY",
    "ALEX",
]


@app.middleware("http")
async def no_cache_response_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


class PreviewLine(BaseModel):
    productCode: str = Field(min_length=1)
    description: str | None = None
    quantity: Decimal = Field(gt=0)
    unitPrice: Decimal = Field(ge=0)
    taxInd: str | None = "N"


class OrderPreviewRequest(BaseModel):
    lines: list[PreviewLine]
    discount: Decimal = Field(default=Decimal("0"), ge=0)
    discountAmount: Decimal | None = Field(default=None, ge=0)
    handling: Decimal = Field(default=Decimal("0"), ge=0)
    taxRate: Decimal = Field(default=Decimal("0"), ge=0)


class DraftHeader(BaseModel):
    soNumber: int | None = None
    customerId: str | None = None
    customerName: str | None = None
    phone: str | None = None
    orderDate: str
    shipDate: str | None = None
    orderType: str | None = None
    shipVia: str | None = None
    salesOne: str | None = None
    salesTwo: str | None = None
    warehouse: str | None = None
    storeNumber: str | None = None
    poNumber: str | None = None
    refNumber: str | None = None
    attention: str | None = None
    billName: str | None = None
    billAddress: str | None = None
    billCity: str | None = None
    billState: str | None = None
    billZip: str | None = None
    shipName: str | None = None
    shipAddress: str | None = None
    shipCity: str | None = None
    shipState: str | None = None
    shipZip: str | None = None
    terms: str | None = None
    termsDays: Decimal | None = None
    termsCod: str | None = None
    email: str | None = None


class DraftLine(PreviewLine):
    lineId: int | None = None
    lineNumber: int | None = None
    commLine: int | None = None
    warehouse: str | None = None
    pack: Decimal | None = None
    unitName: str | None = None
    shippedQty: Decimal = Decimal("0")
    available: Decimal | None = None
    shipDate: str | None = None


class DraftTotals(BaseModel):
    subtotal: Decimal = Field(ge=0)
    taxableAmount: Decimal = Field(default=Decimal("0"), ge=0)
    taxRate: Decimal = Field(default=Decimal("0"), ge=0)
    tax: Decimal = Field(default=Decimal("0"), ge=0)
    discount: Decimal = Field(default=Decimal("0"), ge=0)
    handling: Decimal = Field(default=Decimal("0"), ge=0)
    total: Decimal = Field(ge=0)


class DraftSaveRequest(BaseModel):
    header: DraftHeader
    lines: list[DraftLine] = Field(min_length=1)
    totals: DraftTotals


CLARION_DATE_BASE = date(1800, 12, 28)
SO_MIN_NUMBER = int(os.getenv("ORDER_SO_MIN_NUMBER", "1"))
SO_MAX_NUMBER = int(os.getenv("ORDER_SO_MAX_NUMBER", "500000"))
PRODUCT_IMAGE_DIR = os.getenv("ORDER_PRODUCT_IMAGE_DIR", r"Z:\oms_gmw\oms picture")
WEB_ORDER_SOLD_TO = "Order by IPad"


def to_clarion_date(value: str | None) -> int:
    if not value:
        return 0
    return (date.fromisoformat(value) - CLARION_DATE_BASE).days


def from_clarion_date(value: int | float | None) -> str | None:
    if not value:
        return None
    return (CLARION_DATE_BASE + timedelta(days=int(value))).isoformat()


def current_clarion_time() -> int:
    now = datetime.now()
    seconds = now.hour * 3600 + now.minute * 60 + now.second
    return seconds * 100 + int(now.microsecond / 10000)


def clean_code(value: str | None, fallback: str = "") -> str:
    text = (value or fallback or "").strip()
    return text


def oms_legacy_order_phone_value(phone: str | None, fallback_customer_id: str | None = None) -> Decimal:
    def digits_only(value: str | None) -> str:
        return "".join(ch for ch in clean_code(value) if ch.isdigit())

    digits = digits_only(phone)
    if len(digits) < 7:
        fallback_digits = digits_only(fallback_customer_id)
        digits = fallback_digits if len(fallback_digits) >= 7 else ""
    if not digits:
        return Decimal("0")
    return Decimal(digits[:15])


def lookup_code_variants(value: str | None) -> list[str]:
    raw = clean_code(value)
    if not raw:
        return []

    variants: list[str] = []

    def add(candidate: str | None) -> None:
        text = clean_code(candidate)
        if text and text not in variants:
            variants.append(text)

    add(raw)
    compact = "".join(raw.split())
    add(compact)

    if compact.isdigit():
        without_leading_zero = compact.lstrip("0")
        add(without_leading_zero)

        # Some product UPC values in OMS are stored without the UPC/EAN check digit
        # or without a leading zero. Scanners may send the full printed barcode.
        if len(compact) >= 12:
            add(compact[:-1])
        if without_leading_zero and len(without_leading_zero) >= 12:
            add(without_leading_zero[:-1])
        if compact.startswith("0"):
            add(compact[1:])
            if len(compact) > 12:
                add(compact[1:-1])

    return variants


def customer_unit_price(product: dict, customer_type: int | None = None) -> float:
    price_by_customer_type = {
        0: ["retailPrice"],
        1: ["retailPrice"],
        2: ["corporatePrice", "retailPrice"],
        3: ["wholesalePrice", "retailPrice"],
        4: ["wholesalePrice2", "wholesalePrice", "retailPrice"],
        5: ["wholesalePrice3", "wholesalePrice2", "wholesalePrice", "retailPrice"],
    }
    fallback_fields = ["retailPrice", "wholesalePrice", "wholesalePrice2", "wholesalePrice3", "corporatePrice"]
    fields = price_by_customer_type.get(customer_type, fallback_fields)

    for field in [*fields, *fallback_fields]:
        value = product.get(field)
        if value is None:
            continue
        price = float(value)
        if price > 0:
            return price
    return 0.0


def product_price_levels(product: dict) -> list[dict[str, float | str]]:
    levels = [
        ("L1", "retailPrice"),
        ("L2", "corporatePrice"),
        ("L3", "wholesalePrice"),
        ("L4", "wholesalePrice2"),
        ("L5", "wholesalePrice3"),
    ]
    return [
        {
            "label": label,
            "field": field,
            "price": float(product.get(field) or 0),
        }
        for label, field in levels
    ]


def safe_product_image_path(product_code: str) -> str | None:
    base_dir = os.path.abspath(PRODUCT_IMAGE_DIR)
    product = clean_code(product_code)
    if not product:
        return None
    for extension in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        candidate = os.path.abspath(os.path.join(base_dir, f"{product}{extension}"))
        if os.path.commonpath([base_dir, candidate]) != base_dir:
            continue
        if os.path.isfile(candidate):
            return candidate
    return None


def format_city_state_zip(city: str | None, state: str | None, zip_code: str | None) -> str:
    city_text = clean_code(city)
    state_text = clean_code(state)
    zip_text = clean_code(zip_code)
    state_zip = " ".join(part for part in [state_text, zip_text] if part)
    return ", ".join(part for part in [city_text, state_zip] if part)


def get_ship_code(ship_desc: str | None) -> int:
    if not ship_desc:
        return 0
    row = query_one(
        """
        SELECT TOP 1 TYPE_NUM AS shipCode
        FROM dbo.ctrfile2
        WHERE LTRIM(RTRIM(SHIP_DESC)) = ?
        ORDER BY TYPE_NUM
        """,
        (ship_desc.strip(),),
    )
    return int(row["shipCode"]) if row and row.get("shipCode") is not None else 0


def get_product_cost(product_code: str, warehouse: str) -> dict:
    return query_one(
        """
        SELECT TOP 1
            AVG_COST AS avgCost,
            ORDER_QTY AS orderQty
        FROM dbo.inv_data
        WHERE LTRIM(RTRIM(PROD_CD)) = ?
          AND LTRIM(RTRIM(WHS_NUM)) = ?
        """,
        (product_code.strip(), warehouse.strip()),
    ) or {}


def cursor_one(cursor, sql: str, params: tuple = ()) -> dict | None:
    cursor.execute(sql, params)
    columns = [column[0] for column in cursor.description or []]
    row = cursor.fetchone()
    if row is None:
        return None
    return {columns[index]: row[index] for index in range(len(columns))}


def cursor_all(cursor, sql: str, params: tuple = ()) -> list[dict]:
    cursor.execute(sql, params)
    columns = [column[0] for column in cursor.description or []]
    return [
        {columns[index]: row[index] for index in range(len(columns))}
        for row in cursor.fetchall()
    ]


def acquire_transaction_lock(cursor, resource: str) -> None:
    cursor.execute(
        """
        SET NOCOUNT ON;
        DECLARE @result int;
        EXEC @result = sp_getapplock
            @Resource = ?,
            @LockMode = 'Exclusive',
            @LockOwner = 'Transaction',
            @LockTimeout = 5000;
        SELECT @result AS lockResult;
        """,
        (resource,),
    )
    lock_result = None
    while True:
        if cursor.description:
            lock_result = cursor.fetchone()
            break
        if not cursor.nextset():
            break
    if lock_result is None or int(lock_result[0]) < 0:
        raise RuntimeError(f"Could not lock transaction resource: {resource}")


def get_ship_code_for_transaction(cursor, ship_desc: str | None) -> int:
    if not ship_desc:
        return 0
    row = cursor_one(
        cursor,
        """
        SELECT TOP 1 TYPE_NUM AS shipCode
        FROM dbo.ctrfile2
        WHERE LTRIM(RTRIM(SHIP_DESC)) = ?
        ORDER BY TYPE_NUM
        """,
        (ship_desc.strip(),),
    )
    return int(row["shipCode"]) if row and row.get("shipCode") is not None else 0


def get_order_ship_address_flag_for_transaction(
    cursor,
    customer_id: str,
    store_number: str | None,
    ship_name: str | None,
    ship_address: str | None,
) -> str:
    if clean_code(store_number):
        return "S"

    row = cursor_one(
        cursor,
        """
        SELECT TOP 1
            SHP_CUS_NM AS shipCustomerName,
            SHP_ADDRESS AS shipAddress,
            SHP_ADDRESS2 AS shipAddress2,
            SHP_CITY AS shipCity,
            SHP_STATE AS shipState,
            SHP_ZIP AS shipZip
        FROM dbo.customer
        WHERE CUS_ID = ?
        """,
        (customer_id,),
    ) or {}
    has_customer_ship_to = any(
        clean_code(row.get(field))
        for field in ("shipCustomerName", "shipAddress", "shipAddress2", "shipCity", "shipState", "shipZip")
    )
    if has_customer_ship_to:
        return "N"
    if clean_code(ship_name or ship_address):
        return "Y"
    return ""


def get_product_cost_for_transaction(cursor, product_code: str, warehouse: str) -> dict:
    return cursor_one(
        cursor,
        """
        SELECT TOP 1
            AVG_COST AS avgCost,
            ORDER_QTY AS orderQty
        FROM dbo.inv_data WITH (UPDLOCK, HOLDLOCK)
        WHERE LTRIM(RTRIM(PROD_CD)) = ?
          AND LTRIM(RTRIM(WHS_NUM)) = ?
        """,
        (product_code.strip(), warehouse.strip()),
    ) or {}


def require_inventory_rows_for_transaction(cursor, lines: list[DraftLine], fallback_warehouse: str) -> None:
    missing_products: list[str] = []
    for line in lines:
        product_code = clean_code(line.productCode)
        warehouse = clean_code(line.warehouse, fallback_warehouse)
        row = cursor_one(
            cursor,
            """
            SELECT TOP 1 PROD_CD AS productCode
            FROM dbo.inv_data WITH (UPDLOCK, HOLDLOCK)
            WHERE LTRIM(RTRIM(PROD_CD)) = ?
              AND LTRIM(RTRIM(WHS_NUM)) = ?
            """,
            (product_code, warehouse),
        )
        if row is None:
            missing_products.append(f"{product_code}/{warehouse}")
    if missing_products:
        raise HTTPException(status_code=400, detail=f"Missing local inventory rows: {', '.join(missing_products)}")


def reserve_next_local_so_number(cursor) -> int:
    acquire_transaction_lock(cursor, "local-oms-next-so")

    row = cursor.execute(
        """
        WITH occupied AS
        (
            SELECT ORD_NUM AS so_number
            FROM dbo.orders WITH (UPDLOCK, HOLDLOCK)
            WHERE ORD_NUM >= ? AND ORD_NUM < ?
            UNION
            SELECT CAST(ORD_NUM AS int) AS so_number
            FROM dbo.ord_log WITH (UPDLOCK, HOLDLOCK)
            WHERE ORD_NUM >= ? AND ORD_NUM < ?
            UNION
            SELECT ORD_NUM AS so_number
            FROM dbo.order2e WITH (UPDLOCK, HOLDLOCK)
            WHERE ORD_NUM >= ? AND ORD_NUM < ?
        ),
        candidates AS
        (
            SELECT CAST(? AS int) AS so_number
            UNION
            SELECT so_number + 1
            FROM occupied
            WHERE so_number + 1 < ?
        )
        SELECT TOP 1
            c.so_number AS soNumber
        FROM candidates AS c
        WHERE c.so_number >= ?
          AND c.so_number < ?
          AND NOT EXISTS (
            SELECT 1
            FROM occupied AS o
            WHERE o.so_number = c.so_number
        )
        ORDER BY c.so_number
        """,
        (
            SO_MIN_NUMBER,
            SO_MAX_NUMBER,
            SO_MIN_NUMBER,
            SO_MAX_NUMBER,
            SO_MIN_NUMBER,
            SO_MAX_NUMBER,
            SO_MIN_NUMBER,
            SO_MAX_NUMBER,
            SO_MIN_NUMBER,
            SO_MAX_NUMBER,
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("Could not generate a free S/O number.")
    return int(row[0])


def next_candidate_so_number() -> dict:
    has_web_drafts = query_one("SELECT OBJECT_ID(N'dbo.web_order_drafts', N'U') AS objectId")
    draft_filter = (
        """
          AND NOT EXISTS (
              SELECT 1
              FROM dbo.web_order_drafts AS d
              WHERE d.so_number = c.so_number
          )
        """
        if has_web_drafts and has_web_drafts.get("objectId") is not None
        else ""
    )
    row = query_one(
        f"""
        WITH occupied AS
        (
            SELECT ORD_NUM AS so_number
            FROM dbo.orders
            WHERE ORD_NUM >= ? AND ORD_NUM < ?
            UNION
            SELECT CAST(ORD_NUM AS int) AS so_number
            FROM dbo.ord_log
            WHERE ORD_NUM >= ? AND ORD_NUM < ?
            UNION
            SELECT ORD_NUM AS so_number
            FROM dbo.order2e
            WHERE ORD_NUM >= ? AND ORD_NUM < ?
        ),
        candidates AS
        (
            SELECT CAST(? AS int) AS so_number
            UNION
            SELECT so_number + 1
            FROM occupied
            WHERE so_number + 1 < ?
        )
        SELECT TOP 1
            c.so_number AS soNumber,
            (SELECT MAX(ORD_NUM) FROM dbo.orders WHERE ORD_NUM > 0 AND ORD_NUM < ?) AS maxExistingSo,
            CAST(? AS int) AS minCandidateSo
        FROM candidates AS c
        WHERE c.so_number >= ?
          AND c.so_number < ?
          AND NOT EXISTS (SELECT 1 FROM occupied AS o WHERE o.so_number = c.so_number)
        {draft_filter}
        ORDER BY c.so_number
        """,
        (
            SO_MIN_NUMBER,
            SO_MAX_NUMBER,
            SO_MIN_NUMBER,
            SO_MAX_NUMBER,
            SO_MIN_NUMBER,
            SO_MAX_NUMBER,
            SO_MIN_NUMBER,
            SO_MAX_NUMBER,
            SO_MAX_NUMBER,
            SO_MIN_NUMBER,
            SO_MIN_NUMBER,
            SO_MAX_NUMBER,
        ),
    )
    if row is None:
        raise HTTPException(status_code=500, detail="Could not generate a free S/O number.")
    return row


@app.on_event("startup")
def startup_check() -> None:
    assert_safe_database()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": "app-write-enabled" if app_write_enabled() else "read-only"}


@app.get("/health/db")
def health_db() -> dict:
    return {
        "status": "ok",
        "mode": "app-write-enabled" if app_write_enabled() else "read-only",
        "writeEnabled": app_write_enabled(),
        "database": assert_safe_database(),
    }


@app.get("/api/lookups/order-types")
def order_types(limit: int = Query(default=100, ge=1, le=300)) -> list[dict]:
    return query(
        f"""
        SELECT TOP {limit}
            TYPE_NUM AS typeNumber,
            SHIP_DESC AS shipDescription
        FROM dbo.ctrfile2
        WHERE NULLIF(LTRIM(RTRIM(SHIP_DESC)), '') IS NOT NULL
        ORDER BY TYPE_NUM
        """
    )


@app.get("/api/lookups/sales")
def sales_people(limit: int = Query(default=200, ge=1, le=500)) -> list[dict]:
    return [
        {
            "salesNumber": user,
            "companyName": user,
            "name": user,
            "commissionRate": 0,
            "active": "Y",
        }
        for user in SALES_USERS[:limit]
    ]


@app.get("/api/lookups/warehouses")
def warehouses() -> list[dict]:
    return query(
        """
        SELECT
            WHS_NUM AS warehouseNumber,
            WHS_DESC AS warehouseDescription
        FROM dbo.whs_file
        WHERE NULLIF(LTRIM(RTRIM(WHS_NUM)), '') IS NOT NULL
        ORDER BY WHS_NUM
        """
    )


@app.get("/api/orders/next-so")
def next_sales_order_number() -> dict:
    row = next_candidate_so_number()
    return {
        "soNumber": row["soNumber"],
        "maxExistingSo": row["maxExistingSo"],
        "minCandidateSo": row["minCandidateSo"],
        "reserved": False,
        "note": "Candidate only. It is not reserved until an order save transaction writes the order.",
    }


@app.get("/api/customers/search")
def search_customers(q: str = Query(min_length=2), limit: int = Query(default=20, ge=1, le=50)) -> list[dict]:
    like = f"%{q.strip()}%"
    digits = "".join(ch for ch in q if ch.isdigit())
    digit_like = f"%{digits}%" if digits else like
    return query(
        f"""
        SELECT TOP {limit}
            CUS_ID AS customerId,
            CUS_NM AS customerName,
            CUS_TYPE AS customerType,
            PHONE AS phone,
            PHONE_2 AS phone2,
            PHONE_3 AS phone3,
            ADDRESS AS billAddress,
            CITY AS billCity,
            STATE AS billState,
            ZIP AS billZip,
            TERM_DESC AS termDescription,
            TERMS_DAY AS termsDay,
            TERMS_COD AS termsCod,
            SALES_NUM AS salesNumber,
            SHIP_DESC AS shipDescription,
            ATTN AS attention,
            EMAIL_ADR AS email
        FROM dbo.customer
        WHERE
            CUS_ID LIKE ?
            OR CUS_NM LIKE ?
            OR PHONE LIKE ?
            OR PHONE_2 LIKE ?
            OR PHONE_3 LIKE ?
            OR REPLACE(REPLACE(REPLACE(PHONE, '-', ''), ' ', ''), '(', '') LIKE ?
        ORDER BY CUS_ID
        """,
        (like, like, like, like, like, digit_like),
    )


@app.get("/api/customers/{customer_id}")
def get_customer(customer_id: str) -> dict:
    row = query_one(
        """
        SELECT TOP 1
            CUS_ID AS customerId,
            CUS_NM AS customerName,
            CUS_TYPE AS customerType,
            PHONE AS phone,
            PHONE_2 AS phone2,
            PHONE_3 AS phone3,
            ADDRESS AS billAddress,
            ADDRESS2 AS billAddress2,
            CITY AS billCity,
            STATE AS billState,
            ZIP AS billZip,
            SHP_CUS_NM AS shipCustomerName,
            SHP_ADDRESS AS shipAddress,
            SHP_ADDRESS2 AS shipAddress2,
            SHP_CITY AS shipCity,
            SHP_STATE AS shipState,
            SHP_ZIP AS shipZip,
            SHP_PHONE AS shipPhone,
            TERM_DESC AS termDescription,
            TERMS_DAY AS termsDay,
            TERMS_COD AS termsCod,
            SALES_NUM AS salesNumber,
            SALES_NUM2 AS salesNumber2,
            SHIP_DESC AS shipDescription,
            ATTN AS attention,
            EMAIL_ADR AS email,
            TAX_RATE AS taxRate,
            DISCOUNT AS discount
        FROM dbo.customer
        WHERE CUS_ID = ?
        """,
        (customer_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return row


@app.get("/api/customers/{customer_id}/stores")
def get_customer_stores(customer_id: str) -> list[dict]:
    return query(
        """
        SELECT
            CUS_ID AS customerId,
            STR_NUM AS storeNumber,
            CUS_NM AS storeName,
            ADDRESS AS address,
            ADDRESS2 AS address2,
            CITY AS city,
            STATE AS state,
            ZIP AS zip,
            PHONE AS phone,
            SALES_NUM AS salesNumber,
            SHIP_DESC AS shipDescription
        FROM dbo.chn_str
        WHERE CUS_ID = ?
        ORDER BY
            CASE WHEN STR_NUM NOT LIKE '%[^0-9]%' THEN 0 ELSE 1 END,
            CASE WHEN STR_NUM NOT LIKE '%[^0-9]%' THEN LEN(LTRIM(RTRIM(STR_NUM))) ELSE 0 END,
            LTRIM(RTRIM(STR_NUM))
        """,
        (customer_id,),
    )


@app.get("/api/customers/{customer_id}/orders")
def get_customer_orders(customer_id: str, limit: int = Query(default=80, ge=1, le=1000)) -> list[dict]:
    rows = query(
        f"""
        SELECT TOP {limit}
            o.ORD_NUM AS soNumber,
            o.ORD_DT AS orderDateRaw,
            o.SHIP_DT AS shipDateRaw,
            o.ORD_AMT AS orderAmount,
            o.INVS_TAX AS tax,
            o.HANDL_FEE AS handling,
            o.DISCOUNT AS discount,
            o.PO_NUM AS poNumber,
            o.REF_NUM AS refNumber,
            o.STORE_NUM AS storeNumber,
            o.SHIP_DESC AS shipVia,
            o.SALES_NUM AS salesOne,
            o.ATTN AS attention,
            COUNT(l.PROD_CD) AS itemCount
        FROM dbo.orders AS o
        LEFT JOIN dbo.ord_log AS l ON l.ORD_NUM = o.ORD_NUM
        WHERE o.CUS_ID = ?
        GROUP BY
            o.ORD_NUM, o.ORD_DT, o.SHIP_DT, o.ORD_AMT, o.INVS_TAX, o.HANDL_FEE,
            o.DISCOUNT, o.PO_NUM, o.REF_NUM, o.STORE_NUM, o.SHIP_DESC,
            o.SALES_NUM, o.ATTN
        ORDER BY o.ORD_DT DESC, o.ORD_NUM DESC
        """,
        (customer_id,),
    )
    for row in rows:
        row["orderDate"] = from_clarion_date(row.pop("orderDateRaw", None))
        row["shipDate"] = from_clarion_date(row.pop("shipDateRaw", None))
    return rows


@app.get("/api/customers/{customer_id}/purchases")
def search_customer_purchases(
    customer_id: str,
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=80, ge=1, le=1000),
) -> list[dict]:
    text = q.strip()
    like = f"%{text}%"
    params: tuple[object, ...]
    where = "o.CUS_ID = ?"
    if text:
        where += """
            AND (
                l.PROD_CD LIKE ?
                OR COALESCE(NULLIF(LTRIM(RTRIM(l.UT_DESC)), ''), i.DESCRIP, '') LIKE ?
                OR i.DESCRIP LIKE ?
                OR CONVERT(varchar(20), o.ORD_NUM) LIKE ?
            )
        """
        params = (customer_id, like, like, like, like)
    else:
        params = (customer_id,)

    rows = query(
        f"""
        SELECT TOP {limit}
            o.ORD_NUM AS soNumber,
            o.ORD_DT AS orderDateRaw,
            l.NT_NUM AS lineNumber,
            l.PROD_CD AS productCode,
            COALESCE(NULLIF(LTRIM(RTRIM(l.UT_DESC)), ''), i.DESCRIP, '') AS description,
            l.ORDER_QTY AS quantity,
            l.DEF_UT AS unitName,
            l.UNIT_PRS AS unitPrice,
            l.ORDER_QTY * l.UNIT_PRS AS extAmount,
            o.PO_NUM AS poNumber,
            o.STORE_NUM AS storeNumber,
            o.SALES_NUM AS salesOne
        FROM dbo.orders AS o
        INNER JOIN dbo.ord_log AS l ON l.ORD_NUM = o.ORD_NUM
        LEFT JOIN dbo.inv AS i ON i.PROD_CD = l.PROD_CD
        WHERE {where}
        ORDER BY o.ORD_DT DESC, o.ORD_NUM DESC, l.NT_NUM
        """,
        params,
    )
    for row in rows:
        row["orderDate"] = from_clarion_date(row.pop("orderDateRaw", None))
    return rows


@app.get("/api/products/search")
def search_products(q: str = Query(min_length=2), limit: int = Query(default=30, ge=1, le=100)) -> list[dict]:
    like = f"%{q.strip()}%"
    return query(
        f"""
        SELECT TOP {limit}
            i.PROD_CD AS productCode,
            i.DESCRIP AS description,
            i.UNIT_NM AS unitName,
            i.RETAIL_PRS AS retailPrice,
            i.WHOLE_PRS AS wholesalePrice,
            i.TAX_IND AS taxInd,
            i.UPC_CD AS upc,
            i.IMAGE_NM AS imageName
        FROM dbo.inv AS i
        WHERE
            i.PROD_CD LIKE ?
            OR i.DESCRIP LIKE ?
            OR i.UPC_CD LIKE ?
        ORDER BY i.PROD_CD
        """,
        (like, like, like),
    )


@app.get("/api/products/lookup/{code}")
def lookup_product(code: str, customerType: int | None = Query(default=None, ge=0, le=99)) -> dict:
    variants = lookup_code_variants(code)
    if not variants:
        raise HTTPException(status_code=404, detail="Product not found")
    placeholders = ", ".join("?" for _ in variants)
    product = query_one(
        f"""
        SELECT TOP 1
            i.PROD_CD AS productCode,
            i.DESCRIP AS description,
            i.DESCRIP1 AS description1,
            i.DESCRIP2 AS description2,
            i.UNIT_NM AS unitName,
            i.RETAIL_PRS AS retailPrice,
            i.WHOLE_PRS AS wholesalePrice,
            i.WHOLE_PRS2 AS wholesalePrice2,
            i.WHOLE_PRS3 AS wholesalePrice3,
            i.CORP_PRS AS corporatePrice,
            i.PRICE_1 AS price1,
            i.PRICE_2 AS price2,
            i.PRICE_3 AS price3,
            i.PRICE_4 AS price4,
            i.PRICE_5 AS price5,
            i.PRICE_6 AS price6,
            i.TAX_IND AS taxInd,
            i.PC_CASE AS piecesPerCase,
            i.BOX_CASE AS boxesPerCase,
            i.UPC_CD AS upc,
            iu.UPC_CD AS matchedUpc,
            i.UNIT_COLOR AS showroomLocation,
            i.IMAGE_NM AS imageName
        FROM dbo.inv AS i
        LEFT JOIN dbo.inv_upc AS iu ON iu.PROD_CD = i.PROD_CD AND LTRIM(RTRIM(iu.UPC_CD)) IN ({placeholders})
        WHERE LTRIM(RTRIM(i.PROD_CD)) IN ({placeholders})
           OR LTRIM(RTRIM(i.UPC_CD)) IN ({placeholders})
           OR LTRIM(RTRIM(iu.UPC_CD)) IN ({placeholders})
        ORDER BY
            CASE WHEN LTRIM(RTRIM(i.PROD_CD)) = ? THEN 0 ELSE 1 END,
            i.PROD_CD
        """,
        (*variants, *variants, *variants, *variants, variants[0]),
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    product["customerType"] = customerType
    product["unitPrice"] = customer_unit_price(product, customerType)
    product["priceLevels"] = product_price_levels(product)
    product["imageUrl"] = f"/api/products/{product['productCode'].strip()}/image"

    inventory = query(
        """
        SELECT
            WHS_NUM AS warehouseNumber,
            SUM(ISNULL(IN_STOCK, 0)) AS inStock,
            SUM(ISNULL(ORDER_QTY, 0)) AS orderQty,
            SUM(ISNULL(IN_STOCK, 0) - ISNULL(ORDER_QTY, 0)) AS availableQty,
            SUM(ISNULL(ON_ORDER_QTY, 0)) AS onOrderQty,
            SUM(ISNULL(BACK_QTY, 0)) AS backQty,
            MAX(NULLIF(LTRIM(RTRIM(INV_LOC)), '')) AS inventoryLocation
        FROM dbo.inv_data
        WHERE PROD_CD = ?
        GROUP BY WHS_NUM
        ORDER BY WHS_NUM
        """,
        (product["productCode"],),
    )
    product["inventory"] = inventory
    product["inventorySummary"] = {
        "w1": next((row for row in inventory if str(row.get("warehouseNumber")).strip() == "1"), None),
        "w2": next((row for row in inventory if str(row.get("warehouseNumber")).strip() == "2"), None),
        "w6": next((row for row in inventory if str(row.get("warehouseNumber")).strip() == "6"), None),
        "totalAvailable": sum(
            float(row.get("availableQty") or 0)
            for row in inventory
            if str(row.get("warehouseNumber")).strip() in {"1", "2", "6"}
        ),
    }
    return product


@app.get("/api/products/{product_code}/image")
def product_image(product_code: str):
    path = safe_product_image_path(product_code)
    if path is None:
        raise HTTPException(status_code=404, detail="Product image not found")
    return FileResponse(path)


@app.post("/api/orders/preview")
def preview_order(payload: OrderPreviewRequest) -> dict:
    subtotal = sum(line.quantity * line.unitPrice for line in payload.lines)
    taxable = sum(
        line.quantity * line.unitPrice
        for line in payload.lines
        if (line.taxInd or "").strip().upper() in {"Y", "T", "1"}
    )
    if payload.discountAmount is not None:
        discount_amount = min(payload.discountAmount, subtotal)
        discount_rate = Decimal("0") if subtotal == 0 else discount_amount * Decimal("100") / subtotal
    else:
        discount_rate = payload.discount
        discount_amount = subtotal * discount_rate / Decimal("100")
    merchandise_total = subtotal - discount_amount
    taxable_after_discount = taxable * (Decimal("100") - discount_rate) / Decimal("100")
    tax = taxable_after_discount * payload.taxRate / Decimal("100")
    total = merchandise_total + payload.handling + tax

    return {
        "lineCount": len(payload.lines),
        "subtotal": round(float(subtotal), 2),
        "taxableAmount": round(float(taxable_after_discount), 2),
        "tax": round(float(tax), 2),
        "discountRate": round(float(discount_rate), 6),
        "discountAmount": round(float(discount_amount), 2),
        "merchandiseTotal": round(float(merchandise_total), 2),
        "handling": round(float(payload.handling), 2),
        "total": round(float(total), 2),
        "mode": "preview-only",
    }


@app.post("/api/drafts")
def save_draft(payload: DraftSaveRequest) -> dict:
    subtotal = sum(line.quantity * line.unitPrice for line in payload.lines)
    if round(float(subtotal), 2) != round(float(payload.totals.subtotal), 2):
        raise HTTPException(status_code=400, detail="Draft subtotal does not match line totals.")

    with write_transaction() as conn:
        cursor = conn.cursor()
        draft_id = insert_and_get_id(
            cursor,
            """
            INSERT INTO dbo.web_order_drafts
            (
                so_number, customer_id, customer_name, phone, order_date, ship_date,
                order_type, ship_via, sales_one, sales_two, warehouse,
                po_number, ref_number, attention,
                bill_name, bill_address, bill_city, bill_state, bill_zip,
                ship_name, ship_address, ship_city, ship_state, ship_zip,
                terms, terms_days, terms_cod, email,
                subtotal, taxable_amount, tax_rate, tax_amount, discount, handling, total
            )
            VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.header.soNumber,
                payload.header.customerId,
                payload.header.customerName,
                payload.header.phone,
                payload.header.orderDate,
                payload.header.shipDate,
                payload.header.orderType,
                payload.header.shipVia,
                payload.header.salesOne,
                payload.header.salesTwo,
                payload.header.warehouse,
                payload.header.poNumber,
                payload.header.refNumber,
                payload.header.attention,
                payload.header.billName,
                payload.header.billAddress,
                payload.header.billCity,
                payload.header.billState,
                payload.header.billZip,
                payload.header.shipName,
                payload.header.shipAddress,
                payload.header.shipCity,
                payload.header.shipState,
                payload.header.shipZip,
                payload.header.terms,
                payload.header.termsDays,
                payload.header.termsCod,
                payload.header.email,
                payload.totals.subtotal,
                payload.totals.taxableAmount,
                payload.totals.taxRate,
                payload.totals.tax,
                payload.totals.discount,
                payload.totals.handling,
                payload.totals.total,
            ),
        )

        for index, line in enumerate(payload.lines, start=1):
            cursor.execute(
                """
                INSERT INTO dbo.web_order_draft_lines
                (
                    draft_id, line_no, product_code, description, warehouse, pack,
                    tax_ind, order_qty, unit_name, shipped_qty, unit_price,
                    ext_amount, available_qty, ship_date
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    index,
                    line.productCode,
                    line.description,
                    line.warehouse,
                    line.pack,
                    line.taxInd,
                    line.quantity,
                    line.unitName,
                    line.shippedQty,
                    line.unitPrice,
                    line.quantity * line.unitPrice,
                    line.available,
                    line.shipDate,
                ),
            )

    saved = query_one(
        """
        SELECT
            id AS id,
            draft_no AS draftNo,
            so_number AS soNumber,
            status AS status,
            customer_id AS customerId,
            customer_name AS customerName,
            total AS total,
            created_at AS createdAt
        FROM dbo.web_order_drafts
        WHERE id = ?
        """,
        (draft_id,),
    )
    return {"status": "saved", "draft": saved}


@app.get("/api/oms/orders/{so_number}")
@app.get("/api/local-oms/orders/{so_number}")
def get_local_oms_order(so_number: int) -> dict:
    header = query_one(
        """
        SELECT TOP 1
            o.ORD_NUM AS soNumber,
            o.CUS_ID AS customerId,
            c.CUS_NM AS customerName,
            COALESCE(
                NULLIF(LTRIM(RTRIM(c.PHONE)), ''),
                NULLIF(CONVERT(varchar(19), CONVERT(decimal(21,0), ISNULL(o.CUS_SHIP_CHG, 0))), '0'),
                NULLIF(LTRIM(RTRIM(o.CUS_SHIP_TEL2)), ''),
                ''
            ) AS phone,
            c.PHONE AS billPhone,
            c.PHONE_2 AS billFax,
            c.SHP_PHONE AS shipPhone,
            c.SHP_PHONE_2 AS shipFax,
            o.CUS_SHIP_TEL2 AS orderShipPhone,
            o.CUS_SHIP_CHG AS legacyOrderPhone,
            o.ORD_DT AS orderDateRaw,
            o.SHIP_DT AS shipDateRaw,
            o.SHIP_DESC AS shipVia,
            o.SALES_NUM AS salesOne,
            o.SALES_NUM2 AS salesTwo,
            o.WHS_NUM AS warehouse,
            o.STORE_NUM AS storeNumber,
            o.PO_NUM AS poNumber,
            o.REF_NUM AS refNumber,
            o.ATTN AS attention,
            o.ORD_BY AS orderTaken,
            o.ORDER_BY AS orderBy,
            COALESCE(NULLIF(CASE WHEN LTRIM(RTRIM(o.SOLD_TO)) = 'Order by IPad' THEN '' ELSE LTRIM(RTRIM(o.SOLD_TO)) END, ''), c.CUS_NM, '') AS billName,
            c.ADDRESS AS billAddress,
            c.ADDRESS2 AS billAddress2,
            c.CITY AS billCity,
            c.STATE AS billState,
            c.ZIP AS billZip,
            COALESCE(NULLIF(LTRIM(RTRIM(o.SP_ADR)), ''), NULLIF(LTRIM(RTRIM(o.SP_CUS_NM)), ''), c.SHP_CUS_NM, c.CUS_NM, '') AS shipName,
            COALESCE(NULLIF(LTRIM(RTRIM(o.SP_ADR_2)), ''), c.SHP_ADDRESS, c.ADDRESS, '') AS shipAddress,
            COALESCE(NULLIF(LTRIM(RTRIM(o.SP_ADR_22)), ''), c.SHP_ADDRESS2, c.ADDRESS2, '') AS shipAddress2,
            COALESCE(NULLIF(LTRIM(RTRIM(o.SP_ADR_CT)), ''), c.SHP_CITY, c.CITY, '') AS shipCity,
            COALESCE(NULLIF(LTRIM(RTRIM(o.SP_ADR_ST)), ''), c.SHP_STATE, c.STATE, '') AS shipState,
            COALESCE(NULLIF(LTRIM(RTRIM(o.SP_ADR_ZP)), ''), c.SHP_ZIP, c.ZIP, '') AS shipZip,
            o.TERM_DESC AS terms,
            o.TERMS_DAY AS termsDays,
            o.TERMS_COD AS termsCod,
            COALESCE(NULLIF(LTRIM(RTRIM(o.EMAIL_ADR)), ''), c.EMAIL_ADR, '') AS email,
            o.TAX_RATE AS taxRate,
            o.INVS_TAX AS tax,
            o.DISCOUNT AS discount,
            o.HANDL_FEE AS handling,
            o.ORD_AMT AS orderAmount,
            o.TAXABLE_AMT AS taxableAmount
        FROM dbo.orders AS o
        LEFT JOIN dbo.customer AS c ON c.CUS_ID = o.CUS_ID
        WHERE o.ORD_NUM = ?
        """,
        (so_number,),
    )
    if header is None:
        raise HTTPException(status_code=404, detail=f"S/O {so_number} not found.")

    lines = query(
        """
        SELECT
            l.Id AS lineId,
            l.NT_NUM AS lineNumber,
            l.COMM_LN AS commLine,
            l.PROD_CD AS productCode,
            COALESCE(NULLIF(LTRIM(RTRIM(l.UT_DESC)), ''), i.DESCRIP, '') AS description,
            l.WHS_NUM AS warehouse,
            l.PC_UNIT AS pack,
            l.TAX_IND AS taxInd,
            l.ORDER_QTY AS quantity,
            l.DEF_UT AS unitName,
            l.INVS_QTY AS shippedQty,
            l.PCK_QTY AS pickedQty,
            l.UNIT_PRS AS unitPrice,
            l.ORDER_QTY * l.UNIT_PRS AS extAmount,
            ISNULL(d.IN_STOCK, 0) - ISNULL(d.ORDER_QTY, 0) AS available,
            d.INV_LOC AS location,
            i.CLASS_CD AS classCode,
            i.UNIT_COLOR AS unitColor,
            COALESCE(NULLIF(i.SHIP_WT, 0), NULLIF(i.UT_WT, 0), 0) AS unitWeight,
            CASE
                WHEN COALESCE(i.UNIT_SF, 0) <> 0 THEN i.UNIT_SF
                WHEN COALESCE(i.PC_CASE, 0) <> 0 THEN COALESCE(i.CASE_SF, 0) / NULLIF(i.PC_CASE, 0)
                ELSE COALESCE(i.CASE_SF, 0)
            END AS unitVolume,
            i.CASE_WT AS caseWeight,
            i.CASE_SF AS caseVolume,
            l.SHIP_DT AS shipDateRaw
        FROM dbo.ord_log AS l
        LEFT JOIN dbo.inv AS i ON i.PROD_CD = l.PROD_CD
        LEFT JOIN dbo.inv_data AS d
            ON d.PROD_CD = l.PROD_CD
           AND LTRIM(RTRIM(d.WHS_NUM)) = LTRIM(RTRIM(l.WHS_NUM))
        WHERE l.ORD_NUM = ?
        ORDER BY l.NT_NUM
        """,
        (so_number,),
    )

    header["orderDate"] = from_clarion_date(header.pop("orderDateRaw", None)) or date.today().isoformat()
    header["shipDate"] = from_clarion_date(header.pop("shipDateRaw", None)) or header["orderDate"]
    subtotal = sum((line.get("quantity") or 0) * (line.get("unitPrice") or 0) for line in lines)
    discount_amount = subtotal * (header.get("discount") or 0) / 100
    header["subtotal"] = round(float(subtotal), 2)
    header["discountAmount"] = round(float(discount_amount), 2)
    header["total"] = round(
        float(subtotal - discount_amount + (header.get("handling") or 0) + (header.get("tax") or 0)),
        2,
    )

    for line in lines:
        line["shipDate"] = from_clarion_date(line.pop("shipDateRaw", None)) or header["shipDate"]

    return {"header": header, "lines": lines}


@app.get("/api/oms/orders/{so_number}/invoice.pdf")
@app.get("/api/local-oms/orders/{so_number}/invoice.pdf")
def print_local_oms_invoice(so_number: int) -> Response:
    pdf = invoice_pdf(get_local_oms_order(so_number))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="invoice-{so_number}.pdf"'},
    )


@app.get("/api/oms/orders/{so_number}/picking-list.pdf")
@app.get("/api/local-oms/orders/{so_number}/picking-list.pdf")
def print_local_oms_picking_list(so_number: int) -> Response:
    pdf = picking_list_pdf(get_local_oms_order(so_number))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="picking-list-{so_number}.pdf"'},
    )


@app.post("/api/oms/orders/{so_number}/print/{kind}")
@app.post("/api/local-oms/orders/{so_number}/print/{kind}")
def print_local_oms_order_document(so_number: int, kind: str) -> dict:
    order = get_local_oms_order(so_number)
    if kind == "invoice":
        pdf = invoice_pdf(order)
    elif kind == "picking-list":
        pdf = picking_list_pdf(order)
    else:
        raise HTTPException(status_code=400, detail="Print kind must be invoice or picking-list.")
    try:
        return print_pdf_bytes(pdf, so_number=so_number, kind=kind)
    except PrintError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/oms/orders")
@app.post("/api/local-oms/orders")
def save_local_oms_order(payload: DraftSaveRequest) -> dict:
    subtotal = sum(line.quantity * line.unitPrice for line in payload.lines)
    if round(float(subtotal), 2) != round(float(payload.totals.subtotal), 2):
        raise HTTPException(status_code=400, detail="Order subtotal does not match line totals.")

    customer_id = clean_code(payload.header.customerId)
    if not customer_id:
        raise HTTPException(status_code=400, detail="Customer is required.")

    warehouse = clean_code(payload.header.warehouse, "1")
    order_date = to_clarion_date(payload.header.orderDate)
    ship_date = to_clarion_date(payload.header.shipDate or payload.header.orderDate)
    order_time = current_clarion_time()
    discount_rate = Decimal(payload.totals.discount or 0)
    discount_amount = subtotal * discount_rate / Decimal("100")
    merchandise_total = subtotal - discount_amount
    user_code = clean_code(payload.header.salesOne, "WEB")[:10]
    legacy_order_phone_number = oms_legacy_order_phone_value(payload.header.phone, customer_id)
    ship_desc = clean_code(payload.header.shipVia)
    store_number = clean_code(payload.header.storeNumber)[:12]
    ship_city_state_zip = format_city_state_zip(
        payload.header.shipCity,
        payload.header.shipState,
        payload.header.shipZip,
    )[:60]

    with write_transaction() as conn:
        cursor = conn.cursor()
        require_inventory_rows_for_transaction(cursor, payload.lines, warehouse)
        ship_code = get_ship_code_for_transaction(cursor, ship_desc)
        ship_address_flag = get_order_ship_address_flag_for_transaction(
            cursor,
            customer_id,
            store_number,
            payload.header.shipName,
            payload.header.shipAddress,
        )
        so_number = reserve_next_local_so_number(cursor)
        order_columns = [
            "ORD_NUM", "CUS_ID", "ORD_DT", "ORD_AMT", "PAID_AMT", "INVS_TAX", "TAX_RATE",
            "MISC_CHG", "HANDL_FEE", "DISCOUNT", "PAID_BY", "SALES_NUM", "SALES_NUM2",
            "ORD_TIME", "SP_SM_ADR", "PO_NUM", "SHIP_CD", "CLOSE_CD", "SHIP_DT",
            "TERM_DESC", "TERMS_DAY", "TERMS_COD", "CC_PRINT",
            "SP_ADR", "SP_ADR_2", "SP_ADR_22", "SP_ADR_3", "SP_ADR_CT", "SP_ADR_ST", "SP_ADR_ZP",
            "NT_SEL", "COMM_AMT", "COMM_RT", "COMM_AMT2", "COMM_RT2", "CAN_DT", "ATTN",
            "SHIP_DESC", "FOB_DESC", "WHS_NUM", "REF_NUM", "ORD_BY", "CHK_NUM", "ACT_NUM",
            "STORE_NUM", "INVS_NUM", "NUM_CTL", "TAXABLE_AMT", "ORD_TYPE", "COD_DESC",
            "PACK_PRT", "ORD_PRT", "SALES_NUM3", "SALES_NUM4", "COMM_AMT3", "COMM_RT3",
            "COMM_AMT4", "COMM_RT4", "PCK_AMT", "SOUR_DESC", "SP_ADR_CN", "CURRENCY",
            "EXC_RT", "SHIP_CHG", "AUTHRZ_AMT", "EMAIL_ADR", "EMAIL_IND", "COD_CASH",
            "TRK_NUM", "ORDER_BY", "CUS_SHIP_CHG", "DISC_AMT", "UPDT_BY", "UPDT_DT",
            "PCODE", "UPS_ACT", "SP_CUS_NM", "SOLD_TO", "STATUS", "EARN_BONUS",
            "USED_BONUS", "BONUS_BACK", "PAYMT_CD", "CUS_SHIP_TEL2", "REF_NUM2", "DELIVERY_DT",
        ]
        order_values = [
            so_number, customer_id, order_date, merchandise_total, 0, payload.totals.tax, payload.totals.taxRate,
            0, payload.totals.handling, discount_rate, 0, clean_code(payload.header.salesOne)[:4], clean_code(payload.header.salesTwo)[:4],
            order_time, ship_address_flag, clean_code(payload.header.poNumber)[:100], ship_code, 0, ship_date,
            clean_code(payload.header.terms)[:15], payload.header.termsDays or 0, clean_code(payload.header.termsCod)[:1], 0,
            clean_code(payload.header.shipName or payload.header.customerName)[:60], clean_code(payload.header.shipAddress)[:60], "", ship_city_state_zip,
            clean_code(payload.header.shipCity)[:35], clean_code(payload.header.shipState)[:15], clean_code(payload.header.shipZip)[:15],
            "", 0, 0, 0, 0, 0, clean_code(payload.header.attention)[:30],
            ship_desc[:15], "", warehouse[:6], clean_code(payload.header.refNumber)[:20], user_code[:15], 0, 0,
            store_number, 0, 0, payload.totals.taxableAmount, "", clean_code(payload.header.termsCod)[:1],
            0, 0, "", "", 0, 0,
            0, 0, 0, "", clean_code(payload.header.shipState)[:40], "",
            0, 0, 0, clean_code(payload.header.email)[:60], "", clean_code(payload.header.termsCod)[:1],
            "", user_code, legacy_order_phone_number, 0, user_code, order_date,
            "", "", "", WEB_ORDER_SOLD_TO, "", 0,
            0, 0, 0, clean_code(payload.header.phone)[:19], clean_code(payload.header.refNumber)[:20], 0,
        ]
        cursor.execute(
            f"""
            INSERT INTO dbo.orders ({", ".join(f"[{column}]" for column in order_columns)})
            VALUES ({", ".join("?" for _ in order_columns)})
            """,
            tuple(order_values),
        )

        for index, line in enumerate(payload.lines, start=1):
            line_warehouse = clean_code(line.warehouse, warehouse)
            product_code = clean_code(line.productCode)
            costs = get_product_cost_for_transaction(cursor, product_code, line_warehouse)
            log_cost = costs.get("avgCost") or 0
            sale_cost = costs.get("salesCost") or log_cost
            cursor.execute(
                """
                INSERT INTO dbo.ord_log
                (
                    OLG_DT, OLG_TIME, ORD_NUM, CUS_ID, DISCOUNT, INVS_NUM,
                    PROD_CD, ORDER_QTY, CAN_QTY, UNIT_PRS, PROD_COMP, COMM_LN,
                    COMM_RT, INVS_QTY, PCK_QTY, SHIP_DT, NT_NUM, UT_NT,
                    UT_SER, UT_DESC, WHS_NUM, TAX_IND, CAN_DT, LOG_COST,
                    SALE_COST, DISC_LINE, PC_UNIT, DEF_UT, REF_NUM, BO_QTY,
                    LOT_NUM, PUR_NUM, POR_NT_NUM, ORD_NT_KEY, BONUS_PRS
                )
                VALUES
                (?, ?, ?, ?, ?, 0, ?, ?, 0, ?, '', ?, 0, 0, ?, ?, ?, '', '',
                 ?, ?, ?, 0, ?, ?, 0, ?, ?, ?, 0, '', '', 0, 0, 0)
                """,
                (
                    order_date,
                    order_time,
                    so_number,
                    customer_id,
                    discount_rate,
                    product_code,
                    line.quantity,
                    line.unitPrice,
                    index,
                    line.quantity,
                    ship_date,
                    index,
                    clean_code(line.description)[:60],
                    line_warehouse[:6],
                    clean_code(line.taxInd, "N")[:1],
                    log_cost,
                    sale_cost,
                    line.pack or 0,
                    clean_code(line.unitName)[:2],
                    clean_code(payload.header.refNumber)[:12],
                ),
            )
            cursor.execute(
                """
                UPDATE dbo.inv_data
                SET ORDER_QTY = ISNULL(ORDER_QTY, 0) + ?
                WHERE LTRIM(RTRIM(PROD_CD)) = ?
                  AND LTRIM(RTRIM(WHS_NUM)) = ?
                """,
                (line.quantity, product_code, line_warehouse),
            )

        cursor.execute(
            """
            UPDATE dbo.so_divs
            SET
                TYPE_CD = 1,
                INVS_CD = 0
            WHERE ORD_NUM = ?
            """,
            (so_number,),
        )
        if cursor.rowcount == 0:
            cursor.execute(
                """
                INSERT INTO dbo.so_divs
                (
                    ORD_NUM, TYPE_CD, INVS_CD, DIV_CD, PRJ_CD, JOB_CD, DEPT_CD,
                    CLASS_CD, REG_CD, GL_ACT, CHT_NUM, CHT_NUM2, CHT_NUM3,
                    RSV_1, RSV_2, RSV_3, RSV_4
                )
                VALUES (?, 1, 0, '', '', '', '', '', '', '', 0, 0, 0, 0, 0, '', '')
                """,
                (so_number,),
            )
        cursor.execute(
            """
            INSERT INTO dbo.order2e (ORD_NUM, PO_NUM, PO_DT)
            VALUES (?, ?, 0)
            """,
            (so_number, clean_code(payload.header.poNumber)[:22]),
        )

    saved = query_one(
        """
        SELECT
            ORD_NUM AS soNumber,
            CUS_ID AS customerId,
            ORD_DT AS orderDate,
            ORD_AMT AS orderAmount,
            HANDL_FEE AS handling,
            DISCOUNT AS discountRate,
            INVS_NUM AS invoiceNumber
        FROM dbo.orders
        WHERE ORD_NUM = ?
        """,
        (so_number,),
    )
    lines = query(
        """
        SELECT
            ORD_NUM AS soNumber,
            Id AS lineId,
            PROD_CD AS productCode,
            ORDER_QTY AS quantity,
            UNIT_PRS AS unitPrice,
            WHS_NUM AS warehouse,
            NT_NUM AS lineNumber,
            COMM_LN AS commLine
        FROM dbo.ord_log
        WHERE ORD_NUM = ?
        ORDER BY NT_NUM
        """,
        (so_number,),
    )
    return {
        "status": "saved-oms",
        "order": saved,
        "lines": lines,
        "affectedTables": ["orders", "ord_log", "so_divs", "order2e", "inv_data"],
        "note": "Saved to the configured OMS database.",
    }


@app.put("/api/oms/orders/{so_number}")
@app.put("/api/local-oms/orders/{so_number}")
def update_local_oms_order(so_number: int, payload: DraftSaveRequest) -> dict:
    subtotal = sum(line.quantity * line.unitPrice for line in payload.lines)
    if round(float(subtotal), 2) != round(float(payload.totals.subtotal), 2):
        raise HTTPException(status_code=400, detail="Order subtotal does not match line totals.")

    if not payload.header.soNumber or int(payload.header.soNumber) != so_number:
        raise HTTPException(status_code=400, detail="S/O number cannot be changed while editing.")

    customer_id = clean_code(payload.header.customerId)
    if not customer_id:
        raise HTTPException(status_code=400, detail="Customer is required.")

    warehouse = clean_code(payload.header.warehouse, "1")
    order_date = to_clarion_date(payload.header.orderDate)
    ship_date = to_clarion_date(payload.header.shipDate or payload.header.orderDate)
    order_time = current_clarion_time()
    discount_rate = Decimal(payload.totals.discount or 0)
    discount_amount = subtotal * discount_rate / Decimal("100")
    merchandise_total = subtotal - discount_amount
    user_code = clean_code(payload.header.salesOne, "WEB")[:10]
    legacy_order_phone_number = oms_legacy_order_phone_value(payload.header.phone, customer_id)
    ship_desc = clean_code(payload.header.shipVia)
    store_number = clean_code(payload.header.storeNumber)[:12]
    ship_city_state_zip = format_city_state_zip(
        payload.header.shipCity,
        payload.header.shipState,
        payload.header.shipZip,
    )[:60]

    new_quantities: dict[tuple[str, str], Decimal] = {}
    for line in payload.lines:
        key = (clean_code(line.productCode), clean_code(line.warehouse, warehouse))
        new_quantities[key] = new_quantities.get(key, Decimal("0")) + Decimal(line.quantity)

    with write_transaction() as conn:
        cursor = conn.cursor()
        acquire_transaction_lock(cursor, f"local-oms-order-{so_number}")
        if cursor_one(
            cursor,
            "SELECT TOP 1 ORD_NUM FROM dbo.orders WITH (UPDLOCK, HOLDLOCK) WHERE ORD_NUM = ?",
            (so_number,),
        ) is None:
            raise HTTPException(status_code=404, detail=f"S/O {so_number} not found.")
        require_inventory_rows_for_transaction(cursor, payload.lines, warehouse)
        ship_code = get_ship_code_for_transaction(cursor, ship_desc)
        ship_address_flag = get_order_ship_address_flag_for_transaction(
            cursor,
            customer_id,
            store_number,
            payload.header.shipName,
            payload.header.shipAddress,
        )
        old_lines = cursor_all(
            cursor,
            """
            SELECT
                Id AS lineId,
                PROD_CD AS productCode,
                WHS_NUM AS warehouse,
                ISNULL(ORDER_QTY, 0) AS quantity,
                NT_NUM AS lineNumber,
                COMM_LN AS commLine
            FROM dbo.ord_log WITH (UPDLOCK, HOLDLOCK)
            WHERE ORD_NUM = ?
            ORDER BY NT_NUM
            """,
            (so_number,),
        )
        old_by_id = {
            int(line["lineId"]): line
            for line in old_lines
            if line.get("lineId") is not None
        }
        old_quantities: dict[tuple[str, str], Decimal] = {}
        for line in old_lines:
            key = (clean_code(line.get("productCode")), clean_code(line.get("warehouse"), warehouse))
            old_quantities[key] = old_quantities.get(key, Decimal("0")) + Decimal(str(line.get("quantity") or 0))

        cursor.execute(
            """
            UPDATE dbo.orders
            SET
                CUS_ID = ?,
                ORD_DT = ?,
                ORD_AMT = ?,
                INVS_TAX = ?,
                TAX_RATE = ?,
                HANDL_FEE = ?,
                DISCOUNT = ?,
                SALES_NUM = ?,
                SALES_NUM2 = ?,
                ORD_TIME = ?,
                SP_SM_ADR = ?,
                PO_NUM = ?,
                SHIP_CD = ?,
                SHIP_DT = ?,
                TERM_DESC = ?,
                TERMS_DAY = ?,
                TERMS_COD = ?,
                SP_ADR = ?,
                SP_ADR_2 = ?,
                SP_ADR_3 = ?,
                SP_ADR_CT = ?,
                SP_ADR_ST = ?,
                SP_ADR_ZP = ?,
                ATTN = ?,
                SHIP_DESC = ?,
                WHS_NUM = ?,
                REF_NUM = ?,
                ORD_BY = ?,
                STORE_NUM = ?,
                TAXABLE_AMT = ?,
                COD_DESC = ?,
                EMAIL_ADR = ?,
                COD_CASH = ?,
                ORDER_BY = ?,
                CUS_SHIP_CHG = ?,
                DISC_AMT = ?,
                UPDT_BY = ?,
                UPDT_DT = ?,
                SP_CUS_NM = ?,
                SOLD_TO = ?,
                CUS_SHIP_TEL2 = ?,
                REF_NUM2 = ?
            WHERE ORD_NUM = ?
            """,
            (
                customer_id,
                order_date,
                merchandise_total,
                payload.totals.tax,
                payload.totals.taxRate,
                payload.totals.handling,
                discount_rate,
                clean_code(payload.header.salesOne)[:4],
                clean_code(payload.header.salesTwo)[:4],
                order_time,
                ship_address_flag,
                clean_code(payload.header.poNumber)[:100],
                ship_code,
                ship_date,
                clean_code(payload.header.terms)[:15],
                payload.header.termsDays or 0,
                clean_code(payload.header.termsCod)[:1],
                clean_code(payload.header.shipName or payload.header.customerName)[:60],
                clean_code(payload.header.shipAddress)[:60],
                ship_city_state_zip,
                clean_code(payload.header.shipCity)[:35],
                clean_code(payload.header.shipState)[:15],
                clean_code(payload.header.shipZip)[:15],
                clean_code(payload.header.attention)[:30],
                ship_desc[:15],
                warehouse[:6],
                clean_code(payload.header.refNumber)[:20],
                user_code[:15],
                store_number,
                payload.totals.taxableAmount,
                clean_code(payload.header.termsCod)[:1],
                clean_code(payload.header.email)[:60],
                clean_code(payload.header.termsCod)[:1],
                user_code,
                legacy_order_phone_number,
                discount_amount,
                user_code,
                order_date,
                "",
                WEB_ORDER_SOLD_TO,
                clean_code(payload.header.phone)[:19],
                clean_code(payload.header.refNumber)[:20],
                so_number,
            ),
        )

        for key in set(old_quantities) | set(new_quantities):
            delta = new_quantities.get(key, Decimal("0")) - old_quantities.get(key, Decimal("0"))
            if delta:
                cursor.execute(
                    """
                    UPDATE dbo.inv_data
                    SET ORDER_QTY = ISNULL(ORDER_QTY, 0) + ?
                    WHERE LTRIM(RTRIM(PROD_CD)) = ?
                      AND LTRIM(RTRIM(WHS_NUM)) = ?
                    """,
                    (delta, key[0], key[1]),
                )

        retained_line_ids = {
            int(line.lineId)
            for line in payload.lines
            if line.lineId is not None and int(line.lineId) in old_by_id
        }
        for line_id in set(old_by_id) - retained_line_ids:
            cursor.execute("DELETE FROM dbo.ord_log WHERE Id = ?", (line_id,))

        max_existing_line_number = max(
            (int(line.get("lineNumber") or 0) for line in old_lines),
            default=0,
        )
        next_line_number = max_existing_line_number + 1

        for index, line in enumerate(payload.lines, start=1):
            line_warehouse = clean_code(line.warehouse, warehouse)
            product_code = clean_code(line.productCode)
            costs = get_product_cost_for_transaction(cursor, product_code, line_warehouse)
            log_cost = costs.get("avgCost") or 0
            sale_cost = costs.get("salesCost") or log_cost
            if line.lineId is not None and int(line.lineId) in old_by_id:
                cursor.execute(
                    """
                    UPDATE dbo.ord_log
                    SET
                        CUS_ID = ?,
                        DISCOUNT = ?,
                        PROD_CD = ?,
                        ORDER_QTY = ?,
                        UNIT_PRS = ?,
                        COMM_LN = ?,
                        PCK_QTY = ?,
                        SHIP_DT = ?,
                        UT_DESC = ?,
                        WHS_NUM = ?,
                        TAX_IND = ?,
                        LOG_COST = ?,
                        SALE_COST = ?,
                        PC_UNIT = ?,
                        DEF_UT = ?,
                        REF_NUM = ?
                    WHERE Id = ? AND ORD_NUM = ?
                    """,
                    (
                        customer_id,
                        discount_rate,
                        product_code,
                        line.quantity,
                        line.unitPrice,
                        index,
                        line.quantity,
                        ship_date,
                        clean_code(line.description)[:60],
                        line_warehouse[:6],
                        clean_code(line.taxInd, "N")[:1],
                        log_cost,
                        sale_cost,
                        line.pack or 0,
                        clean_code(line.unitName)[:2],
                        clean_code(payload.header.refNumber)[:12],
                        int(line.lineId),
                        so_number,
                    ),
                )
                continue

            line_number = next_line_number
            next_line_number += 1
            cursor.execute(
                """
                INSERT INTO dbo.ord_log
                (
                    OLG_DT, OLG_TIME, ORD_NUM, CUS_ID, DISCOUNT, INVS_NUM,
                    PROD_CD, ORDER_QTY, CAN_QTY, UNIT_PRS, PROD_COMP, COMM_LN,
                    COMM_RT, INVS_QTY, PCK_QTY, SHIP_DT, NT_NUM, UT_NT,
                    UT_SER, UT_DESC, WHS_NUM, TAX_IND, CAN_DT, LOG_COST,
                    SALE_COST, DISC_LINE, PC_UNIT, DEF_UT, REF_NUM, BO_QTY,
                    LOT_NUM, PUR_NUM, POR_NT_NUM, ORD_NT_KEY, BONUS_PRS
                )
                VALUES
                (?, ?, ?, ?, ?, 0, ?, ?, 0, ?, '', ?, 0, 0, ?, ?, ?, '', '',
                 ?, ?, ?, 0, ?, ?, 0, ?, ?, ?, 0, '', '', 0, 0, 0)
                """,
                (
                    order_date,
                    order_time,
                    so_number,
                    customer_id,
                    discount_rate,
                    product_code,
                    line.quantity,
                    line.unitPrice,
                    index,
                    line.quantity,
                    ship_date,
                    line_number,
                    clean_code(line.description)[:60],
                    line_warehouse[:6],
                    clean_code(line.taxInd, "N")[:1],
                    log_cost,
                    sale_cost,
                    line.pack or 0,
                    clean_code(line.unitName)[:2],
                    clean_code(payload.header.refNumber)[:12],
                ),
            )

        cursor.execute("UPDATE dbo.order2e SET PO_NUM = ? WHERE ORD_NUM = ?", (clean_code(payload.header.poNumber)[:22], so_number))
        if cursor.rowcount == 0:
            cursor.execute(
                "INSERT INTO dbo.order2e (ORD_NUM, PO_NUM, PO_DT) VALUES (?, ?, 0)",
                (so_number, clean_code(payload.header.poNumber)[:22]),
            )

    return {
        "status": "updated-oms",
        "order": get_local_oms_order(so_number)["header"],
        "affectedTables": ["orders", "ord_log", "order2e", "inv_data"],
        "note": "Updated the configured OMS database.",
    }


@app.get("/api/drafts/{draft_id}")
def get_draft(draft_id: int) -> dict:
    header = query_one(
        """
        SELECT
            id, draft_no AS draftNo, status, customer_id AS customerId,
            so_number AS soNumber,
            customer_name AS customerName, phone, order_date AS orderDate,
            ship_date AS shipDate, order_type AS orderType, ship_via AS shipVia,
            sales_one AS salesOne, sales_two AS salesTwo, warehouse,
            po_number AS poNumber, ref_number AS refNumber, attention,
            bill_name AS billName, bill_address AS billAddress,
            ship_name AS shipName, ship_address AS shipAddress,
            subtotal, taxable_amount AS taxableAmount, tax_rate AS taxRate,
            tax_amount AS tax, discount, handling, total, created_at AS createdAt
        FROM dbo.web_order_drafts
        WHERE id = ?
        """,
        (draft_id,),
    )
    if header is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    lines = query(
        """
        SELECT
            line_no AS [lineNo], product_code AS [productCode], description,
            warehouse, pack, tax_ind AS [taxInd], order_qty AS quantity,
            unit_name AS [unitName], shipped_qty AS [shippedQty],
            unit_price AS [unitPrice], ext_amount AS [extAmount],
            available_qty AS available, ship_date AS [shipDate]
        FROM dbo.web_order_draft_lines
        WHERE draft_id = ?
        ORDER BY line_no
        """,
        (draft_id,),
    )
    return {"header": header, "lines": lines}
