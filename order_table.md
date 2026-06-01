# OMS Order Table Implementation Notes

Updated: 2026-05-29

This file documents the current table surface used by the web OMS order-entry flow.

## Core Write Tables

| Role | Table | Current use |
|---|---|---|
| Order header | `[dbo].[orders]` | Creates/updates S/O header, customer, addresses, dates, totals, sales, ship via, terms, PO/ref, store/ship-to fields. |
| Order lines | `[dbo].[ord_log]` | Rewrites line items for an order: item number, quantity, unit, price, pack, warehouse, ship date, line amount. |
| Division/accounting row | `[dbo].[so_divs]` | Maintains the sales-order division row expected by OMS. |

## Core Read Tables

| Role | Table | Current use |
|---|---|---|
| Customer master | `[dbo].[customer]` | Bill To, default Ship To, terms, sales, phone, email, and shipping fields. |
| Chain stores | `[dbo].[chn_str]` | Store/Shop list and selected ship-to store for chain-store customers. |
| Product master | `[dbo].[inv]` | Item lookup, description, unit, pack, price, UPC fallback. |
| Alternate UPCs | `[dbo].[inv_upc]` | Additional barcode lookup support. |
| Inventory by warehouse | `[dbo].[inv_data]` | Availability/reference data in the current web order-entry flow. |
| Ship via lookup | `[dbo].[ctrfile2]` | Ship-via choices and code/description mapping. |
| Terms lookup | `[dbo].[ctrfilep]`, `[dbo].[ctrfilet]` | Payment terms, term days, COD flag. |

## Write Safety

- New order and edit order saves are wrapped in a SQL transaction through `backend\app\db.py`.
- SQL Server `sp_getapplock` is used for S/O number assignment and order edit locking.
- `SET XACT_ABORT ON` is enabled before the transaction starts.
- If any part of the save fails, the backend rolls back the whole write.
- The frontend shows new orders as `Draft`; S/O number is assigned only at save time.
- Current S/O search lower bound is configured by `ORDER_SO_MIN_NUMBER`.

## S/O Number Logic

- Current lower bound: `9438`.
- The backend searches for the first usable number at or above that lower bound.
- Missing/non-continuous numbers can be reused.
- Numbers are rejected only when required core OMS order rows conflict with the candidate.
- Small leftover traces alone are not enough to skip a number unless they collide with the write surface.

## Ship-To Logic

The web flow follows the legacy OMS behavior observed from production examples:

- Billing-only customer: save Ship To as the billing address.
- Customer with a separate shipping address: save Ship To as the shipping address.
- Chain-store customer: user chooses Store/Shop; save Ship To from the selected store row.
- Example customer used during investigation: `6467052368`.
- Example legacy order used during investigation: `3003`.

## Current Non-Goals / Watch Areas

- Inventory reservation side effects outside the currently verified order write surface still require caution.
- Print/log side effects outside generated PDFs still need more production before/after evidence.
- Rare commission, approval, tax, freight, payment, and delivery workflows should continue to be verified with snapshots.
