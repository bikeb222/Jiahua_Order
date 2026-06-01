# OMS Desktop Frontend

Desktop/LAN browser version of the OMS sales order entry screen.

## Current State

- Runs on `http://127.0.0.1:5173` on the server PC.
- LAN clients can open `http://<server-ip>:5173`.
- Connects to backend `http://<server-ip>:8008`.
- Uses no-cache headers and no-cache HTML meta tags.
- Keeps the legacy OMS-style layout for keyboard/mouse order entry.
- `Menu` and `Back` buttons are on the right side to reduce accidental clicks.
- `Menu` opens a fresh home/menu window when an order is being edited so users can work with another order.
- `Back` asks for confirmation before leaving an active edit/new order.

## Order Entry Behavior

- New orders display `Draft` until save.
- Save assigns the first usable S/O number from the backend.
- Existing orders can be loaded by List/Edit and updated.
- Customer lookup fills Bill To, Ship To, terms, phone, email, ship via, and sales fields.
- Customers with multiple chain stores use the Store/Shop flow and save the selected ship-to store.
- If a customer only has billing address, Ship To defaults to billing.
- If a customer has a separate shipping address, Ship To uses that shipping address.
- Product scan supports barcode or item number.
- Scanners that send Enter and scanners that send Tab are both supported.
- Order quantity, price, discount, discount amount, tax, handling, total, and balance stay linked.
- Invoice and picking-list PDFs are generated from current order data.

## Run

```powershell
cd C:\Users\info\OneDrive\Desktop\code\order\frontend
python .\dev_server.py
```

Open:

```text
http://127.0.0.1:5173
```

Normally start everything from the project root:

```powershell
.\start_oms_services.ps1
```
