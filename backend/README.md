# OMS Order Backend

Current backend for the web OMS sales order entry system.

## Current State

- Runs on `http://127.0.0.1:8008`.
- Reads from the real OMS database through `ORDER_READ_DB_CONNECTION`.
- Writes through `ORDER_WRITE_DB_CONNECTION` only when the production write flags are enabled.
- Current deployed test configuration uses `DSN=test;DATABASE=omsdata`.
- New order and edit order writes are wrapped in one SQL transaction.
- New S/O assignment and existing S/O edits use SQL Server application locks.
- API responses include no-cache headers so LAN clients do not keep stale order data.
- The desktop frontend uses port `5173`; the iPad/mobile frontend uses port `5174`.

## Run

```powershell
cd C:\Users\info\OneDrive\Desktop\code\order\backend
.\run_backend.ps1
```

Open:

```text
http://127.0.0.1:8008/docs
```

The project-level launcher starts backend, desktop frontend, and iPad frontend together:

```powershell
cd C:\Users\info\OneDrive\Desktop\code\order
.\start_oms_services.ps1
```

Manual restart shortcut:

```text
C:\Users\info\OneDrive\Desktop\code\order\Restart OMS Order Server.cmd
```

## Database Configuration

Configuration lives in:

```text
C:\Users\info\OneDrive\Desktop\code\order\backend\.env
```

Current production test shape:

```text
ORDER_READ_DB_CONNECTION=DSN=test;DATABASE=omsdata;ApplicationIntent=ReadOnly;
ORDER_WRITE_DB_CONNECTION=DSN=test;DATABASE=omsdata;
ORDER_ENABLE_APP_WRITE=true
ORDER_ALLOW_PRODUCTION_READ=true
ORDER_ENABLE_PRODUCTION_OMS_WRITE=true
ORDER_PRODUCTION_WRITE_ACK=I_UNDERSTAND_THIS_WRITES_TO_PRODUCTION_OMS
ORDER_SO_MIN_NUMBER=9438
```

Local development copy shape:

```text
ORDER_DB_CONNECTION=Driver={ODBC Driver 18 for SQL Server};Server=.\OMSDEV;Database=omsdata_local;Trusted_Connection=yes;TrustServerCertificate=yes;
```

Important: frontend code never connects to SQL Server directly. All database access goes through this backend.

## Main APIs

```text
GET  /health
GET  /health/db
GET  /api/lookups/order-types
GET  /api/lookups/sales
GET  /api/lookups/warehouses
GET  /api/customers/search?q=7186639333
GET  /api/customers/{customer_id}
GET  /api/customers/{customer_id}/stores
GET  /api/products/search?q=JH02428
GET  /api/products/lookup/{barcode_or_product_code}
GET  /api/orders/next-so
POST /api/orders/preview
GET  /api/oms/orders/{so_number}
POST /api/oms/orders
PUT  /api/oms/orders/{so_number}
GET  /api/oms/orders/{so_number}/invoice.pdf
GET  /api/oms/orders/{so_number}/picking-list.pdf
```

`/api/local-oms/...` aliases still exist for older frontend calls, but the current deployed flow uses the OMS endpoints.

## Write Rules

- S/O number is still shown as `Draft` while entering a new order.
- On save, the backend looks for the first usable S/O number at or above `ORDER_SO_MIN_NUMBER`.
- Gaps can be reused when the core OMS order rows are not present.
- The save process writes the order header and lines in one transaction.
- If any write step fails, SQL Server rolls the whole order write back.
- Editing an order rewrites the order detail rows for that order inside the same transaction.

## Snapshot Tools

Read-only before/after production capture scripts live in:

```text
backend\get_real_process
```

Use them when comparing real legacy OMS behavior with the web writer.
