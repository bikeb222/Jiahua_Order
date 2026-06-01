# Production OMS Write Readiness

This document records the current production-write posture for the web OMS order entry project.

## Current State

- The backend is now able to read and write the real OMS SQL Server database.
- Current manual-test connection uses `DSN=test;DATABASE=omsdata`.
- Production writes are enabled only when all explicit flags are present in `backend\.env`.
- The current machine has been configured for manual production-write testing.
- The app should still be treated as a controlled pilot until more legacy before/after captures are compared.

Required production write flags:

```text
ORDER_ENABLE_APP_WRITE=true
ORDER_ALLOW_PRODUCTION_READ=true
ORDER_ENABLE_PRODUCTION_OMS_WRITE=true
ORDER_PRODUCTION_WRITE_ACK=I_UNDERSTAND_THIS_WRITES_TO_PRODUCTION_OMS
```

## Transaction And Locking

- New order writes use `write_transaction()`.
- Existing order edits use `write_transaction()`.
- SQL Server runs `SET XACT_ABORT ON` before the transaction starts.
- If any step fails, the backend rolls back the transaction.
- New S/O assignment uses `sp_getapplock`.
- Editing an existing S/O uses an order-specific `sp_getapplock`.
- DB lock timeout is controlled by `ORDER_DB_LOCK_TIMEOUT_MS`.
- Query timeout is controlled by `ORDER_DB_QUERY_TIMEOUT_SECONDS`.

## Current Writer Scope

The web writer currently handles:

- Order header rows in `dbo.orders`.
- Order line rows in `dbo.ord_log`.
- Order division rows in `dbo.so_divs`.
- Existing order load/edit flows through `/api/oms/orders/{so_number}`.
- Invoice and picking-list PDF generation from current order data.
- Customer store/ship-to selection for chain-store customers.

## S/O Number Rule

- New orders show `Draft` while being entered.
- On save, the backend searches for the first usable S/O number.
- The lower bound is `ORDER_SO_MIN_NUMBER`.
- Current lower bound is `9438`.
- Missing numbers can be reused when core order rows are absent.
- Numbers with only small leftover traces are not automatically skipped unless they conflict with required OMS order rows.

## Remaining Verification Work

Keep collecting production snapshots for these scenarios:

- Add order with pickup.
- Add order with delivery, pallet, UPS, and FedEx.
- Discount amount and discount percent combinations.
- Handling/freight/tax combinations.
- Customer with billing only.
- Customer with separate shipping address.
- Chain-store customer with selected store.
- Edit order: delete line, add line, change price, change quantity.
- Large order with many item numbers.

Known areas that still deserve comparison against the legacy OMS:

- Print/log side effects outside the order tables.
- Edge cases around commissions and approval fields.
- Rare tax/freight/payment workflows.
