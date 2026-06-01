from __future__ import annotations

import json
import subprocess
from pathlib import Path
from datetime import datetime

import fitz
import win32con
import win32print
import win32ui
from PIL import Image, ImageWin


INVOICE_PRIMARY = "RICOH MP C3504ex PCL 6"
PICKING_PRIMARY = "Brother HL-L6310DW series"
FALLBACK_PRINTERS = [
    "Canon MF460 II Series UFR II",
    "SHARP MX-B467F XL",
    "Canon MF460 II Series UFR II(JASON)",
]
DENY_NAME_PARTS = ["pdf", "onenote", "zebra", "label", "fax"]
PRINT_SPOOL_DIR = Path(__file__).resolve().parents[1] / "print_spool"
PDF_RENDER_DPI = 400


class PrintError(RuntimeError):
    pass


def _powershell_json(command: str) -> list[dict]:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        raise PrintError(completed.stderr.strip() or "Unable to query printers.")
    output = completed.stdout.strip()
    if not output:
        return []
    data = json.loads(output)
    return data if isinstance(data, list) else [data]


def installed_printers() -> list[dict]:
    return _powershell_json(
        "Get-Printer | "
        "Select-Object Name,PrinterStatus,WorkOffline,PortName,DriverName | "
        "ConvertTo-Json -Depth 3"
    )


def _normal(value: object) -> str:
    return str(value or "").strip().casefold()


def _blocked_printer(name: str) -> bool:
    lower = name.casefold()
    return any(part in lower for part in DENY_NAME_PARTS)


def _printer_usable(printer: dict) -> bool:
    name = str(printer.get("Name") or "")
    status_value = printer.get("PrinterStatus")
    status = _normal(status_value)
    work_offline = str(printer.get("WorkOffline") or "").strip().lower() == "true"
    if not name or _blocked_printer(name) or work_offline:
        return False
    if isinstance(status_value, int):
        return status_value not in {6, 7, 9, 10}
    return status not in {"offline", "error", "not available", "pendingdeletion"}


def available_printers() -> dict[str, dict]:
    return {printer["Name"]: printer for printer in installed_printers() if _printer_usable(printer)}


def _resolve_printer_name(available: dict[str, dict], preferred: str) -> str | None:
    if preferred in available:
        return preferred
    preferred_lower = preferred.casefold()
    for name in available:
        if name.casefold() == preferred_lower:
            return name
    for name in available:
        if name.casefold().startswith(preferred_lower):
            return name
    return None


def candidate_printers(kind: str, available: dict[str, dict]) -> list[str]:
    primary = INVOICE_PRIMARY if kind == "invoice" else PICKING_PRIMARY
    secondary = PICKING_PRIMARY if kind == "invoice" else INVOICE_PRIMARY
    ordered = [primary, secondary, *FALLBACK_PRINTERS]
    resolved: list[str] = []
    for printer in ordered:
        name = _resolve_printer_name(available, printer)
        if name and name not in resolved:
            resolved.append(name)
    return resolved


def _save_audit_pdf(pdf: bytes, *, so_number: int, kind: str) -> Path:
    PRINT_SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = PRINT_SPOOL_DIR / f"{kind}-{so_number}-{stamp}.pdf"
    path.write_bytes(pdf)
    return path


def _pixmap_to_image(pixmap: fitz.Pixmap) -> Image.Image:
    mode = "RGBA" if pixmap.alpha else "RGB"
    image = Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples)
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


def _render_pdf_pages(pdf: bytes) -> list[Image.Image]:
    document = fitz.open(stream=pdf, filetype="pdf")
    try:
        zoom = PDF_RENDER_DPI / 72
        matrix = fitz.Matrix(zoom, zoom)
        pages: list[Image.Image] = []
        for page in document:
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            pages.append(_pixmap_to_image(pixmap))
        return pages
    finally:
        document.close()


def _print_images(printer_name: str, pages: list[Image.Image], *, doc_name: str) -> int:
    if not pages:
        raise PrintError("PDF has no printable pages.")

    printer_handle = win32print.OpenPrinter(printer_name)
    try:
        attributes = win32print.GetPrinter(printer_handle, 2)
        status = int(attributes.get("Status") or 0)
        if status:
            raise PrintError(f"Printer status is not ready: {status}")
    finally:
        win32print.ClosePrinter(printer_handle)

    dc = win32ui.CreateDC()
    dc.CreatePrinterDC(printer_name)
    try:
        printable_width = dc.GetDeviceCaps(win32con.HORZRES)
        printable_height = dc.GetDeviceCaps(win32con.VERTRES)
        job_id = dc.StartDoc(doc_name)
        for image in pages:
            scale = min(printable_width / image.width, printable_height / image.height)
            width = int(image.width * scale)
            height = int(image.height * scale)
            left = int((printable_width - width) / 2)
            top = int((printable_height - height) / 2)

            dc.StartPage()
            ImageWin.Dib(image).draw(dc.GetHandleOutput(), (left, top, left + width, top + height))
            dc.EndPage()
        dc.EndDoc()
        return int(job_id or 0)
    except Exception:
        try:
            dc.AbortDoc()
        except Exception:
            pass
        raise
    finally:
        dc.DeleteDC()


def print_pdf_bytes(pdf: bytes, *, so_number: int, kind: str) -> dict:
    if kind not in {"invoice", "picking-list"}:
        raise PrintError(f"Unsupported print kind: {kind}")
    available = available_printers()
    candidates = candidate_printers(kind, available)
    if not candidates:
        raise PrintError("No available order printers found.")

    audit_path = _save_audit_pdf(pdf, so_number=so_number, kind=kind)
    pages = _render_pdf_pages(pdf)
    last_error = ""
    for printer_name in candidates:
        try:
            job_id = _print_images(
                printer_name,
                pages,
                doc_name=f"OMS {kind} S/O {so_number}",
            )
            return {
                "status": "queued",
                "kind": kind,
                "soNumber": so_number,
                "printer": printer_name,
                "jobId": job_id,
                "pages": len(pages),
                "candidates": candidates,
                "auditPdf": str(audit_path),
            }
        except Exception as exc:
            last_error = f"{printer_name}: {exc}"
    raise PrintError(last_error or "Unable to print PDF.")
