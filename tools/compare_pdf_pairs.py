from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import fitz
from PIL import Image, ImageChops, ImageStat


def render_pdf(path: Path, out_dir: Path, zoom: float) -> list[Path]:
    doc = fitz.open(path)
    rendered: list[Path] = []
    matrix = fitz.Matrix(zoom, zoom)
    for index, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        out_path = out_dir / f"{path.stem}_p{index}.png"
        pix.save(out_path)
        rendered.append(out_path)
    return rendered


def image_metrics(a_path: Path, b_path: Path, diff_path: Path) -> dict:
    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    width = max(a.width, b.width)
    height = max(a.height, b.height)
    canvas_a = Image.new("RGB", (width, height), "white")
    canvas_b = Image.new("RGB", (width, height), "white")
    canvas_a.paste(a, (0, 0))
    canvas_b.paste(b, (0, 0))
    diff = ImageChops.difference(canvas_a, canvas_b)
    diff.save(diff_path)
    stat = ImageStat.Stat(diff)
    rms = math.sqrt(sum(value * value for value in stat.rms) / len(stat.rms))
    bbox = diff.getbbox()
    changed_pixels = 0
    if bbox:
        gray = diff.convert("L")
        changed_pixels = sum(1 for value in gray.getdata() if value > 12)
    return {
        "rms": round(rms, 4),
        "diff_bbox": bbox,
        "changed_pixels_over_threshold": changed_pixels,
        "pixel_count": width * height,
        "changed_percent_over_threshold": round(changed_pixels / (width * height) * 100, 4),
    }


def font_summary(path: Path) -> dict:
    doc = fitz.open(path)
    fonts: dict[str, dict] = {}
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    name = span.get("font", "")
                    size = round(float(span.get("size", 0)), 2)
                    item = fonts.setdefault(name, {"count": 0, "sizes": set()})
                    item["count"] += 1
                    item["sizes"].add(size)
    return {
        name: {"count": data["count"], "sizes": sorted(data["sizes"])}
        for name, data in sorted(fonts.items())
    }


def compare_pair(pdf: Path, reference: Path, out_dir: Path, zoom: float) -> dict:
    rendered = render_pdf(pdf, out_dir, zoom)
    rendered_ref = render_pdf(reference, out_dir, zoom)
    pages = []
    for index in range(max(len(rendered), len(rendered_ref))):
        current_page = rendered[index] if index < len(rendered) else None
        reference_page = rendered_ref[index] if index < len(rendered_ref) else None
        if current_page and reference_page:
            diff_path = out_dir / f"{pdf.stem}_vs_{reference.stem}_p{index + 1}_diff.png"
            metrics = image_metrics(current_page, reference_page, diff_path)
            metrics["current_png"] = str(current_page)
            metrics["reference_png"] = str(reference_page)
            metrics["diff_png"] = str(diff_path)
        else:
            metrics = {
                "missing_current": current_page is None,
                "missing_reference": reference_page is None,
            }
        metrics["page"] = index + 1
        pages.append(metrics)
    return {
        "current_pdf": str(pdf),
        "reference_pdf": str(reference),
        "page_count_current": len(rendered),
        "page_count_reference": len(rendered_ref),
        "pages": pages,
        "fonts_current": font_summary(pdf),
        "fonts_reference": font_summary(reference),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-dir", default="pdf")
    parser.add_argument("--out-dir", default="pdf_compare")
    parser.add_argument("--zoom", type=float, default=2.0)
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = []
    for reference in sorted(pdf_dir.glob("*_oms.pdf")):
        current = reference.with_name(reference.name.replace("_oms.pdf", ".pdf"))
        if current.exists():
            report.append(compare_pair(current, reference, out_dir, args.zoom))

    report_path = out_dir / "pdf-compare-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(report_path)


if __name__ == "__main__":
    main()
