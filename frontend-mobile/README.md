# OMS iPad / Mobile Frontend

iPad-first sales order entry screen for Chrome on the LAN.

## Current State

- Runs on `http://127.0.0.1:5174` on the server PC.
- LAN/iPad URL is `http://<server-ip>:5174`.
- Current deployed example: `http://192.168.1.168:5174/`.
- Target device is iPad Chrome with screen resolution around `2360 x 1640`.
- Connects to backend `http://<server-ip>:8008`.
- Uses no-cache headers and no-cache HTML meta tags.

## Layout

- Header/order/customer section is optimized for iPad landscape.
- Fields wrap when there is not enough width; overlapping fields should be treated as a layout bug.
- Main grid keeps `Ln`, `Item #`, `Pack`, `QTY`, `UM`, `Price`, `EXT`, and delete visible.
- `Description` receives the remaining width and truncates only when necessary.
- Clicking a product description shows the full description.
- Bottom amount fields use the same readable font size as the top order fields.
- `Ship Date` is a plain text date field so iPad Chrome does not display Chinese localized date text.

## Scan Mode

- `Scan Mode` hides the customer/order detail section after customer information is loaded.
- Scan mode keeps the scan input fixed at the top.
- Product list scrolls in the middle.
- Total and `Exit Scan Mode` stay at the bottom with extra bottom padding for the minimized iPad keyboard area.
- The scan input can be used with scanner Enter or scanner Tab.
- The input confirmation button beside scan entry can be used for manual item number entry.

## Custom Keyboards

System keyboard use is intentionally avoided for order-entry fields.

- Numeric keypads exist for customer phone, S/O menu number entry, QTY, discount, discount amount, tax, and handling.
- Price uses a numeric keypad with decimal point.
- Scan/item input uses an alphanumeric keypad.
- Product-code keypad supports the symbols seen in current item numbers: space, `(`, `)`, `+`, `-`, `.`, `/`.
- All floating keypads support click-to-toggle: tap the same field again to hide it, tap again to show it.
- Numeric keypad bottom row is `DEL`, `0`, `OK`.
- `DEL` removes one character.
- `OK` accepts the value, hides the keypad, and returns focus to Scan/Item when appropriate.

## Run

```powershell
cd C:\Users\info\OneDrive\Desktop\code\order\frontend-mobile
python .\dev_server.py
```

Open:

```text
http://127.0.0.1:5174
```

Normally start everything from the project root:

```powershell
.\start_oms_services.ps1
```
