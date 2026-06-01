from __future__ import annotations

import os
from datetime import datetime
from io import BytesIO
from math import ceil
from pathlib import Path
from textwrap import wrap
from typing import Any

from reportlab.graphics.barcode import code128
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


PAGE_W, PAGE_H = letter
LEFT = 18
RIGHT = PAGE_W - 18
INVOICE_COLS = [LEFT, 150, 197, 236, 285, 312, 498, 540, RIGHT]
INVOICE_DESC_WIDTH = INVOICE_COLS[6] - INVOICE_COLS[5] - 8
INVOICE_ROW_START_Y = 492
INVOICE_TABLE_BOTTOM = 148
INVOICE_ROW_LEADING = 10
INVOICE_ROW_HEIGHT = 14.3
INVOICE_BODY_FONT_SIZE = 8
INVOICE_DESC_FONT_SIZE = 7.8
FONT_REGULAR = "Arial"
FONT_BOLD = "Arial-Bold"
FONT_ITALIC = "Arial-Italic"
FONT_BOLD_ITALIC = "Arial-BoldItalic"
FONT_NARROW = "ArialNarrow"
FONT_NARROW_BOLD = "ArialNarrow-Bold"
FONT_NARROW_ITALIC = "ArialNarrow-Italic"
FONT_CODE39 = "C39Medium36ptLJ3"


def register_oms_fonts() -> None:
    global FONT_REGULAR, FONT_BOLD, FONT_ITALIC, FONT_BOLD_ITALIC, FONT_NARROW, FONT_NARROW_BOLD, FONT_NARROW_ITALIC, FONT_CODE39
    fonts = {
        FONT_REGULAR: "arial.ttf",
        FONT_BOLD: "arialbd.ttf",
        FONT_ITALIC: "ariali.ttf",
        FONT_BOLD_ITALIC: "arialbi.ttf",
        FONT_NARROW: "ARIALN.TTF",
        FONT_NARROW_BOLD: "ARIALNB.TTF",
        FONT_NARROW_ITALIC: "ARIALNI.TTF",
        FONT_CODE39: "C39M36L3.TTF",
    }
    windows_fonts = Path("C:/Windows/Fonts")
    try:
        for name, filename in fonts.items():
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(windows_fonts / filename)))
    except Exception:
        FONT_REGULAR = "Helvetica"
        FONT_BOLD = "Helvetica-Bold"
        FONT_ITALIC = "Helvetica-Oblique"
        FONT_BOLD_ITALIC = "Helvetica-BoldOblique"
        FONT_NARROW = FONT_REGULAR
        FONT_NARROW_BOLD = FONT_BOLD
        FONT_NARROW_ITALIC = FONT_ITALIC
        FONT_CODE39 = ""


register_oms_fonts()


def money(value: Any) -> str:
    return f"{float(value or 0):,.2f}"


def qty(value: Any) -> str:
    number = float(value or 0)
    return f"{int(number)}" if number.is_integer() else f"{number:.2f}"


def qty_decimal(value: Any) -> str:
    return f"{float(value or 0):.2f}"


def text(value: Any) -> str:
    return str(value or "").strip()


def first_text(*values: Any) -> str:
    for value in values:
        cleaned = text(value)
        if cleaned:
            return cleaned
    return ""


def phone(value: Any) -> str:
    raw = text(value)
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw


def phone_from_customer_id(value: Any) -> str:
    digits = "".join(ch for ch in text(value) if ch.isdigit())
    return phone(digits) if len(digits) in {10, 11} else ""


def header_phone(h: dict, ship: bool = False) -> str:
    if ship:
        return first_text(
            phone(h.get("orderShipPhone")),
            phone(h.get("shipPhone")),
            phone(h.get("phone")),
            phone(h.get("billPhone")),
            phone_from_customer_id(h.get("customerId")),
        )
    return first_text(
        phone(h.get("billPhone")),
        phone(h.get("phone")),
        phone_from_customer_id(h.get("customerId")),
    )


def header_fax(h: dict, ship: bool = False) -> str:
    return "(000) 000-0000"


def city_state_zip(city: Any, state: Any, zip_code: Any) -> str:
    left = ", ".join(part for part in [text(city), text(state)] if part)
    return " ".join(part for part in [left, text(zip_code)] if part)


def print_stamp(use_24h: bool = False) -> str:
    now = datetime.now()
    if use_24h:
        return f"{now.month}/{now.day}/{now.year}  {now.hour:02d}:{now.minute:02d}"
    hour = now.hour % 12 or 12
    return f"{now.month}/{now.day}/{now.year}  {hour}:{now.minute:02d}{now.strftime('%p')}"


def fmt_date(value: Any) -> str:
    raw = text(value)
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        year, month, day = raw[:10].split("-")
        return f"{int(month)}/{int(day)}/{year}"
    return raw


def draw_text(c: Canvas, x: float, y: float, value: Any, size: int = 8, bold: bool = False, align: str = "left", font_name: str | None = None) -> None:
    c.setFont(font_name or (FONT_BOLD if bold else FONT_REGULAR), size)
    value = text(value)
    if align == "right":
        c.drawRightString(x, y, value)
    elif align == "center":
        c.drawCentredString(x, y, value)
    else:
        c.drawString(x, y, value)


def draw_wrapped(c: Canvas, x: float, y: float, width_chars: int, value: Any, size: int = 8, leading: int = 9, bold: bool = False, font_name: str | None = None) -> float:
    lines = wrap(text(value), width_chars) or [""]
    for line in lines[:3]:
        draw_text(c, x, y, line, size=size, bold=bold, font_name=font_name)
        y -= leading
    return y


def wrap_to_width(value: Any, width: float, font_name: str = FONT_REGULAR, size: float = 8, max_lines: int = 3) -> list[str]:
    words = text(value).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdfmetrics.stringWidth(candidate, font_name, size) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        remaining = word
        while remaining and pdfmetrics.stringWidth(remaining, font_name, size) > width:
            split_at = 1
            for index in range(1, len(remaining) + 1):
                if pdfmetrics.stringWidth(remaining[:index], font_name, size) > width:
                    break
                split_at = index
            lines.append(remaining[:split_at])
            remaining = remaining[split_at:]
        current = remaining
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines] or [""]


def line(c: Canvas, x1: float, y1: float, x2: float, y2: float, shade: float = 0.72) -> None:
    c.setStrokeColor(colors.Color(shade, shade, shade))
    c.setLineWidth(0.45)
    c.line(x1, y1, x2, y2)


def dark_line(c: Canvas, x1: float, y1: float, x2: float, y2: float) -> None:
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.line(x1, y1, x2, y2)


def box(c: Canvas, x: float, y: float, w: float, h: float) -> None:
    c.setStrokeColor(colors.Color(0.72, 0.72, 0.72))
    c.setLineWidth(0.45)
    c.rect(x, y, w, h, stroke=1, fill=0)


def draw_company_header(c: Canvas, title: str, order: dict, page_no: int, page_count: int, italic: bool = False) -> None:
    font = FONT_BOLD_ITALIC if italic else FONT_BOLD
    c.setFont(font, 16 if italic else 18)
    c.drawCentredString(PAGE_W / 2, 747 if italic else 747, "Jia Hua Trading Inc.")
    draw_text(c, PAGE_W / 2, 735, "WEBSITE: WWW.JIAHUAWHOLESALE.COM", 9, align="center")
    draw_text(c, PAGE_W / 2, 725, "EMAIL: INFO@JIAHUAWHOLESALE.COM", 9, align="center")
    draw_text(c, PAGE_W / 2, 715, "1293 FLUSHING AVE, BROOKLYN, NY 11237", 9, align="center")
    draw_text(c, PAGE_W / 2, 705, "Tel: (347) 689-3533          Fax: (212) 481-2278", 9, align="center")
    draw_order_barcode(c, order)
    c.setFont(FONT_BOLD_ITALIC if italic else FONT_BOLD, 24 if italic else 18)
    c.drawCentredString(PAGE_W / 2, 681, title)
    page_y = 682 if italic else 672
    draw_text(c, 512 if italic else 528, page_y, "Page", 8)
    draw_text(c, 585, page_y, f"{page_no}   of   {page_count}", 8, align="right")
    line(c, LEFT, 671, RIGHT, 671)


def draw_order_barcode(c: Canvas, order: dict) -> None:
    so_number = text(order["header"].get("soNumber", ""))
    if FONT_CODE39:
        c.setFont(FONT_CODE39, 28.02)
        c.drawString(510, 696, f"*{so_number}*")
        return
    barcode = code128.Code128(so_number, barHeight=30, barWidth=0.65)
    barcode.drawOn(c, RIGHT - barcode.width, 696)


def draw_address_block(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    title: str,
    name: str,
    address: list[str],
    tel: str,
    fax: str = "",
    attention: str = "",
) -> None:
    draw_text(c, x + 12, y + 77, title, 8, bold=True)
    box(c, x, y, w, 74)
    draw_text(c, x + 6, y + 61, f"Attn: {text(attention)}", 9)
    draw_text(c, x + 25, y + 49, name, 11, bold=True)
    yy = y + 38
    for row in [text(item) for item in address if text(item)][:3]:
        draw_text(c, x + 25, yy, row, 9)
        yy -= 11
    draw_text(c, x + 6, y + 8, f"Tel:  {tel}", 9)
    draw_text(c, x + 118, y + 8, f"Fax: {fax}", 9)


def bill_address_lines(h: dict) -> list[str]:
    return [
        h.get("billAddress"),
        h.get("billAddress2"),
        city_state_zip(h.get("billCity"), h.get("billState"), h.get("billZip")),
    ]


def ship_address_lines(h: dict) -> list[str]:
    return [
        h.get("shipAddress"),
        h.get("shipAddress2"),
        city_state_zip(h.get("shipCity"), h.get("shipState"), h.get("shipZip")),
    ]


def split_lines(lines: list[dict], per_page: int) -> list[list[dict]]:
    if not lines:
        return [[]]
    return [lines[i : i + per_page] for i in range(0, len(lines), per_page)]


def invoice_description_lines(row: dict) -> list[str]:
    return wrap_to_width(row.get("description"), INVOICE_DESC_WIDTH, FONT_REGULAR, INVOICE_DESC_FONT_SIZE, 2)


def invoice_row_slots(row: dict) -> int:
    return max(1, len(invoice_description_lines(row)))


def invoice_row_height(row: dict) -> float:
    return max(INVOICE_ROW_HEIGHT, len(invoice_description_lines(row)) * 11)


def split_invoice_lines(lines: list[dict]) -> list[list[dict]]:
    if not lines:
        return [[]]
    pages: list[list[dict]] = []
    page: list[dict] = []
    used_height = 0.0
    height_limit = INVOICE_ROW_START_Y - INVOICE_TABLE_BOTTOM - 6
    for row in lines:
        row_height = invoice_row_height(row)
        if page and used_height + row_height > height_limit:
            pages.append(page)
            page = []
            used_height = 0.0
        page.append(row)
        used_height += row_height
    if page:
        pages.append(page)
    return pages


def invoice_print_by(h: dict) -> str:
    return first_text(h.get("salesOne"), os.environ.get("ORDER_PDF_PRINT_BY"), h.get("printBy"))


def ship_attention(h: dict) -> str:
    store_number = text(h.get("storeNumber"))
    return f"Store#: {store_number}" if store_number else text(h.get("attention"))


def invoice_pdf(order: dict) -> bytes:
    pages = split_invoice_lines(order.get("lines", []))
    out = BytesIO()
    c = Canvas(out, pagesize=letter)
    for page_no, page_lines in enumerate(pages, start=1):
        draw_invoice_page(c, order, page_lines, page_no, len(pages))
        c.showPage()
    c.save()
    return out.getvalue()


def draw_invoice_page(c: Canvas, order: dict, lines_: list[dict], page_no: int, page_count: int) -> None:
    h = order["header"]
    draw_company_header(c, "Customer Sales Order", order, page_no, page_count)
    draw_text(c, 486, 684, "S/O No.:", 11, bold=True)
    draw_text(c, 572, 684, h.get("soNumber"), 9, bold=True, align="right")
    draw_text(c, 20, 659, f"Customer No.: {h.get('customerId','')}   Terms: {h.get('terms','')}", 9, bold=True)
    draw_text(c, 280, 659, "Dept  No.:", 9, bold=True)
    draw_text(c, 410, 659, "Cases:", 9, bold=True)
    draw_text(c, 492, 659, "Store No.:", 9, bold=True)
    draw_text(c, 570, 659, h.get("storeNumber"), 9, bold=True, align="right")
    line(c, LEFT, 654, RIGHT, 654)
    draw_address_block(
        c,
        38,
        561,
        270,
        "Sold To",
        text(h.get("billName")),
        bill_address_lines(h),
        header_phone(h),
        header_fax(h),
        h.get("attention"),
    )
    draw_address_block(
        c,
        322,
        561,
        270,
        "Ship To Address:",
        text(h.get("shipName")),
        ship_address_lines(h),
        header_phone(h, ship=True),
        header_fax(h, ship=True),
        ship_attention(h),
    )
    draw_text(c, 415, 638, f"Print By: {invoice_print_by(h)}", 8)
    draw_text(c, 505, 638, f"Date: {print_stamp()}", 8)
    draw_invoice_meta(c, h)
    draw_invoice_table(c, lines_)
    if page_no == page_count:
        draw_invoice_footer(c, h)
    else:
        draw_invoice_terms(c)


def draw_invoice_meta(c: Canvas, h: dict) -> None:
    y1, y2 = 557, 522
    xs = [LEFT, 70, 166, 220, 318, 370, 468, 538, RIGHT]
    labels = ["S/O Date", "P/O No.", "Sales Rep.", "F.O.B.", "Ship Date", "Ship Via", "Cancel Date", "Order By"]
    for x in xs[:-1]:
        line(c, x, y1, x, y2)
    line(c, LEFT, y1, RIGHT, y1)
    line(c, LEFT, 538, RIGHT, 538)
    line(c, LEFT, y2, RIGHT, y2)
    centers = [(xs[i] + xs[i + 1]) / 2 for i in range(len(labels))]
    values = [
        fmt_date(h.get("orderDate")),
        h.get("poNumber"),
        h.get("salesOne"),
        "",
        fmt_date(h.get("shipDate")),
        h.get("shipVia"),
        "/  /",
        first_text(h.get("orderTaken"), h.get("orderBy"), h.get("salesOne")),
    ]
    for i, label in enumerate(labels):
        draw_text(c, centers[i], 545, label, 8, bold=True, align="center")
        value = f"{values[i]} /" if label == "Sales Rep." and values[i] else values[i]
        draw_text(c, centers[i], 527, value, 8, align="center")


def draw_invoice_table(c: Canvas, lines_: list[dict]) -> None:
    top = 522
    cols = INVOICE_COLS
    headers = ["Item No.", "Quantity", "Cases", "LoosePc", "Whs#", "Description", "Unit Price", "Ext.Amount"]
    row_heights = [invoice_row_height(row) for row in lines_]
    bottom = min(INVOICE_TABLE_BOTTOM, INVOICE_ROW_START_Y - sum(row_heights) - 8)
    for x in cols:
        line(c, x, top, x, bottom)
    line(c, LEFT, top, RIGHT, top)
    line(c, LEFT, 504, RIGHT, 504)
    line(c, LEFT, bottom, RIGHT, bottom)
    for i, header in enumerate(headers):
        draw_text(c, (cols[i] + cols[i + 1]) / 2, 509, header, 8.5, bold=True, align="center")
    y = INVOICE_ROW_START_Y
    for row, row_height in zip(lines_, row_heights):
        quantity = float(row.get("quantity") or 0)
        pack = float(row.get("pack") or 0)
        cases = int(quantity // pack) if pack else ""
        loose = quantity % pack if pack else quantity
        draw_text(c, cols[0] + 2, y, row.get("productCode"), INVOICE_BODY_FONT_SIZE)
        draw_text(c, cols[2] - 4, y, qty(quantity), INVOICE_BODY_FONT_SIZE, align="right")
        draw_text(c, cols[3] - 4, y, cases, INVOICE_BODY_FONT_SIZE, align="right")
        draw_text(c, cols[4] - 4, y, "" if loose == 0 else qty_decimal(loose), INVOICE_BODY_FONT_SIZE, align="right")
        draw_text(c, (cols[4] + cols[5]) / 2, y, row.get("warehouse"), INVOICE_BODY_FONT_SIZE, align="center")
        desc_lines = invoice_description_lines(row)
        yy = y
        for desc in desc_lines:
            draw_text(c, cols[5] + 2, yy, desc, INVOICE_DESC_FONT_SIZE)
            yy -= 9
        draw_text(c, cols[7] - 4, y, f"{float(row.get('unitPrice') or 0):.4f}", INVOICE_BODY_FONT_SIZE, align="right")
        draw_text(c, cols[8] - 4, y, money(row.get("extAmount")), INVOICE_BODY_FONT_SIZE, align="right")
        y -= row_height


def draw_invoice_footer(c: Canvas, h: dict) -> None:
    draw_text(c, 28, 132, "Notes:", 8)
    draw_text(c, 430, 136, "Order Amount:", 9, bold=True)
    draw_text(c, 592, 136, money(h.get("subtotal")), 9, bold=True, align="right")
    if float(h.get("discountAmount") or 0):
        draw_text(c, 430, 124, f"Discount {float(h.get('discount') or 0):.2f}%:", 9)
        draw_text(c, 592, 124, f"-{money(h.get('discountAmount'))}", 9, align="right")
    draw_text(c, 430, 112, "Sales Tax", 9)
    draw_text(c, 515, 112, "%:", 9)
    draw_text(c, 592, 112, money(h.get("taxRate")), 9, align="right")
    draw_text(c, 430, 100, "Freight Fee:", 9)
    draw_text(c, 592, 100, money(0), 9, align="right")
    draw_text(c, 430, 88, "Handling:", 9)
    draw_text(c, 592, 88, money(h.get("handling")), 9, align="right")
    draw_text(c, 430, 76, "Total Amount:", 10, bold=True)
    draw_text(c, 592, 76, money(h.get("total")), 10, bold=True, align="right")

    draw_text(c, 22, 78, f"Order Taken: {first_text(h.get('orderTaken'), h.get('orderBy'), h.get('salesOne'))}", 8)
    draw_text(c, 60, 66, "Sales Person:", 8)
    line(c, 140, 64, 260, 64, 0.25)
    draw_text(c, 310, 66, "Price Change Approved By:", 8)
    line(c, 452, 64, 586, 64, 0.25)
    draw_text(c, 60, 55, "Pricing Approved By:", 8)
    line(c, 170, 53, 304, 53, 0.25)
    draw_text(c, 405, 55, "Credit Approved By:", 8)
    line(c, 520, 53, 586, 53, 0.25)
    draw_text(c, 390, 44, "Shipping Approved By:", 8)
    line(c, 520, 42, 586, 42, 0.25)

    draw_invoice_terms(c)


def draw_invoice_terms(c: Canvas) -> None:
    draw_text(c, 32, 35, "1. ALL CLAIMS, REQUESTS FOR ADJUSTMENTS, OR NOTIFICATION OF ERRORS MUST BE MADE IN WRITTEN WITHIN 2 DAYS OF RECEIPT OF", 7.5)
    draw_text(c, 32, 26, "THIS INVOICE, OR CHANGES ARE CONSIDERED ACCEPTED.", 7.5)
    draw_text(c, 32, 17, "2. ANY CHECK RETURNED WILL BE CHARGED AN ADDITIONAL $35.00.", 7.5)
    draw_text(c, 32, 8, "3. ALL MERCHANDISE ARE FINAL SALE, NO REFUND, NO EXCHANGE.    4. THANK YOU FOR YOUR BUSINESS!!", 7.5)


def picking_list_pdf(order: dict) -> bytes:
    lines_for_print = order.get("lines", [])
    pages = split_lines(lines_for_print, 16)
    out = BytesIO()
    c = Canvas(out, pagesize=letter)
    for page_no, page_lines in enumerate(pages, start=1):
        draw_picking_page(c, order, page_lines, page_no, len(pages), lines_for_print)
        c.showPage()
    c.save()
    return out.getvalue()


def draw_picking_page(c: Canvas, order: dict, lines_: list[dict], page_no: int, page_count: int, print_lines: list[dict]) -> None:
    h = order["header"]
    draw_company_header(c, "Pick List", order, page_no, page_count)
    draw_text(c, 20, 659, f"Order No.:    {h.get('soNumber')}       Terms: {h.get('terms','')}", 10, bold=True)
    draw_text(c, 302, 659, "# of Cases:", 10, bold=True)
    draw_text(c, 410, 659, f"Date:  {fmt_date(h.get('orderDate'))}", 10, bold=True)
    draw_text(c, 498, 659, f"Print: {print_stamp(use_24h=True)}", 9)
    line(c, LEFT, 654, RIGHT, 654)
    draw_address_block(
        c,
        26,
        561,
        294,
        "Sold To:",
        text(h.get("billName")),
        bill_address_lines(h),
        header_phone(h),
        header_fax(h),
        h.get("attention"),
    )
    draw_address_block(
        c,
        332,
        561,
        RIGHT - 332,
        "Ship To Address:",
        text(h.get("shipName")),
        ship_address_lines(h),
        header_phone(h, ship=True),
        header_fax(h, ship=True),
        ship_attention(h),
    )
    draw_text(c, 520, 645, f"Processor:    {h.get('salesOne') or ''}", 8)
    draw_picking_meta(c, h)
    draw_picking_table(c, lines_)
    if page_no == page_count:
        draw_picking_footer(c, print_lines)


def draw_picking_meta(c: Canvas, h: dict) -> None:
    y1, y2 = 542, 507
    cols = [LEFT, 110, 225, 292, 342, 420, 482, RIGHT]
    headers = ["Customer ID", "Customer P/O No.", "Order Date", "S/O No.", "Sales Rep.", "Ship Date", "Ship Via"]
    values = [h.get("customerId"), h.get("poNumber"), fmt_date(h.get("orderDate")), h.get("soNumber"), h.get("salesOne"), fmt_date(h.get("shipDate")), h.get("shipVia")]
    for x in cols:
        line(c, x, y1, x, y2)
    line(c, LEFT, y1, RIGHT, y1)
    line(c, LEFT, 523, RIGHT, 523)
    line(c, LEFT, y2, RIGHT, y2)
    for i, header in enumerate(headers):
        draw_text(c, (cols[i] + cols[i + 1]) / 2, 530, header, 9, bold=True, align="center")
        draw_text(c, (cols[i] + cols[i + 1]) / 2, 512, values[i], 10, align="center")


def draw_picking_table(c: Canvas, lines_: list[dict]) -> None:
    top, bottom = 507, 86
    cols = [LEFT, 112, 160, 340, 386, 418, 456, 490, 528, 562, RIGHT]
    headers = ["Item No.", "Loc", "Description", "Class\nColor", "Pc/Cs", "Ship Qty", "Cases", "LoosePc", "Weight", "Volume"]
    for x in cols:
        line(c, x, top, x, bottom)
    line(c, LEFT, top, RIGHT, top)
    line(c, LEFT, 489, RIGHT, 489)
    line(c, LEFT, bottom, RIGHT, bottom)
    for i, header in enumerate(headers):
        parts = header.split("\n")
        yy = 497 if len(parts) == 1 else 498
        for part in parts:
            draw_text(c, (cols[i] + cols[i + 1]) / 2, yy, part, 9, bold=True, align="center", font_name=FONT_BOLD)
            yy -= 8
    y = 477
    for row in lines_:
        quantity = float(row.get("quantity") or 0)
        pack = float(row.get("pack") or 0)
        cases = int(quantity // pack) if pack else ""
        loose = quantity % pack if pack else quantity
        row_weight = quantity * float(row.get("unitWeight") or 0)
        row_volume = quantity * float(row.get("unitVolume") or 0)
        draw_text(c, cols[0] + 2, y, row.get("productCode"), 10, font_name=FONT_REGULAR)
        draw_text(c, cols[0] + 34, y - 13, f"Ws#: {row.get('warehouse') or ''}", 7)
        draw_text(c, cols[1] + 2, y, row.get("location") or "", 10, font_name=FONT_REGULAR)
        draw_wrapped(c, cols[2] + 2, y, 29, row.get("description"), 10, 11, font_name=FONT_REGULAR)
        draw_text(c, (cols[3] + cols[4]) / 2, y, row.get("classCode") or "", 10, align="center", font_name=FONT_REGULAR)
        if text(row.get("classCode")):
            dark_line(c, cols[3] + 8, y - 4, cols[4] - 8, y - 4)
        draw_text(c, (cols[3] + cols[4]) / 2, y - 14, row.get("unitColor") or "", 10, align="center", font_name=FONT_REGULAR)
        draw_text(c, cols[5] - 4, y, f"{pack:.2f}" if pack else "", 10, align="right", font_name=FONT_REGULAR)
        if pack:
            dark_line(c, cols[4] + 12, y - 4, cols[5] - 4, y - 4)
        draw_text(c, cols[5] - 4, y - 14, row.get("unitName") or "", 10, align="right", font_name=FONT_REGULAR)
        draw_text(c, cols[6] - 4, y, qty(quantity), 10, bold=True, align="right", font_name=FONT_BOLD)
        dark_line(c, cols[5] + 12, y - 4, cols[6] - 4, y - 4)
        draw_text(c, cols[7] - 4, y, cases, 10, align="right", font_name=FONT_REGULAR)
        draw_text(c, cols[8] - 4, y, "" if loose == 0 else qty_decimal(loose), 10, align="right", font_name=FONT_REGULAR)
        if loose:
            dark_line(c, cols[7] + 12, y - 4, cols[8] - 4, y - 4)
        draw_text(c, cols[9] - 4, y, money(row_weight) if row_weight else "", 10, align="right", font_name=FONT_REGULAR)
        if row_weight:
            dark_line(c, cols[8] + 12, y - 4, cols[9] - 4, y - 4)
        draw_text(c, cols[10] - 4, y, money(row_volume) if row_volume else "", 10, align="right", font_name=FONT_REGULAR)
        if row_volume:
            dark_line(c, cols[9] + 12, y - 4, cols[10] - 4, y - 4)
        y -= 24


def draw_picking_footer(c: Canvas, lines_: list[dict]) -> None:
    line_count = len(lines_)
    item_qty = sum(float(row.get("quantity") or 0) for row in lines_)
    case_qty = 0
    loose_qty = 0
    weight_total = 0.0
    volume_total = 0.0
    for row in lines_:
        quantity = float(row.get("quantity") or 0)
        pack = float(row.get("pack") or 0)
        if pack:
            case_qty += int(quantity // pack)
            loose_qty += quantity % pack
        else:
            loose_qty += quantity
        weight_total += quantity * float(row.get("unitWeight") or 0)
        volume_total += quantity * float(row.get("unitVolume") or 0)

    y = 63
    draw_text(c, 282, y, "Total:", 13, bold=True)
    draw_text(c, 344, y, qty(line_count), 9, bold=True, align="right")
    dark_line(c, 322, y - 2, 346, y - 2)
    draw_text(c, 374, y, "Items", 10, bold=True)
    draw_text(c, 438, y, qty(item_qty), 9, bold=True, align="right")
    dark_line(c, 418, y - 2, 440, y - 2)
    draw_text(c, 474, y, qty(case_qty), 9, bold=True, align="right")
    dark_line(c, 454, y - 2, 476, y - 2)
    draw_text(c, 516, y, qty(loose_qty), 9, bold=True, align="right")
    dark_line(c, 496, y - 2, 518, y - 2)
    draw_text(c, 554, y, money(weight_total), 9, bold=True, align="right")
    dark_line(c, 522, y - 2, 556, y - 2)
    draw_text(c, 592, y, money(volume_total), 9, bold=True, align="right")
    dark_line(c, 562, y - 2, 594, y - 2)
