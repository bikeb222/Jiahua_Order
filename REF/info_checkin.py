import glob
import os
import sys

from PyQt5.QtCore import QEvent, Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QPixmap, QTransform
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

import barcode_product_scanner as base


WINDOW_WIDTH = 600
WINDOW_HEIGHT = 500
IMAGE_DIR = r"Z:\oms_gmw\oms picture"

base.BASE_FONT_SIZE = 13
base.HEADER_FONT_SIZE = 16
base.TABLE_FONT_SIZE = 14
base.STATUS_FONT_SIZE = 11
base.SMALL_FONT_SIZE = 10
base.DESCRIPTION_FONT_SIZE = 14

CARD_RADIUS = 10
IMAGE_BOX_SIZE = 170
LABEL_BOX_WIDTH = 120
INPUT_WIDTH = 280
TITLE_FONT_SIZE = 16
VALUE_FONT_SIZE = 14
CHIP_TITLE_FONT_SIZE = 15
CHIP_VALUE_FONT_SIZE = 13
ROW_HEIGHT = 72
MULTI_ROW_HEIGHT = 64


class InfoCheckinApp(base.BarcodeProductScannerApp):
    def __init__(self):
        super().__init__()
        self.current_image_path = None
        self.configure_variant()
        self.clear_detail_card()

    def setup_ui(self):
        self.current_image_path = None
        self.setWindowTitle("Info Checkin")
        self.setStyleSheet(
            f"""
            QWidget {{
                font-size: {base.BASE_FONT_SIZE}px;
                background-color: #f6f7fb;
                color: #1c2330;
            }}
            QLineEdit {{
                font-size: {base.BASE_FONT_SIZE}px;
                padding: 6px 10px;
                min-height: 24px;
                border: 1px solid #c9cdd8;
                border-radius: 6px;
                background-color: #ffffff;
            }}
            QPushButton {{
                font-size: {base.BASE_FONT_SIZE}px;
                font-weight: bold;
                padding: 6px 12px;
                min-height: 26px;
                border-radius: 6px;
            }}
            """
        )

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(12, 12, 12, 12)

        lookup_layout = QHBoxLayout()
        lookup_layout.setSpacing(10)

        lookup_label = QLabel("Barcode / Item Code:")
        lookup_label.setFixedWidth(145)
        lookup_layout.addWidget(lookup_label)

        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText("Scan barcode or enter item code, then press Enter...")
        self.scan_input.setFixedWidth(INPUT_WIDTH)
        self.scan_input.returnPressed.connect(self.handle_lookup)
        self.scan_input.installEventFilter(self)
        lookup_layout.addWidget(self.scan_input)

        self.btn_add = QPushButton("Search")
        self.btn_add.setStyleSheet(
            f"background-color: #62c86e; color: white; font-weight: bold; font-size: {base.BASE_FONT_SIZE}px;"
        )
        self.btn_add.clicked.connect(self.handle_lookup)
        lookup_layout.addWidget(self.btn_add)

        self.btn_reset = QPushButton("Clear")
        self.btn_reset.setStyleSheet(
            f"background-color: #ff7d73; color: white; font-weight: bold; font-size: {base.BASE_FONT_SIZE}px;"
        )
        self.btn_reset.clicked.connect(self.reset_table)
        lookup_layout.addWidget(self.btn_reset)
        lookup_layout.addStretch(1)
        main_layout.addLayout(lookup_layout)

        self.status_label = QLabel("Ready. Scan a barcode or enter an item code.")
        self.status_label.setStyleSheet(f"color: #5c6470; padding-left: 2px; font-size: {base.STATUS_FONT_SIZE}px;")
        main_layout.addWidget(self.status_label)

        self.detail_card = QFrame()
        self.detail_card.setStyleSheet(
            f"""
            QFrame {{
                background-color: #ffffff;
                border: 1px solid #dce1ea;
                border-radius: {CARD_RADIUS}px;
            }}
            """
        )
        card_layout = QHBoxLayout(self.detail_card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(12)

        self.image_label = QLabel("No Image")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setFixedSize(IMAGE_BOX_SIZE, IMAGE_BOX_SIZE)
        self.image_label.setStyleSheet(
            f"""
            QLabel {{
                background-color: #f1f3f7;
                border: 1px solid #d8dde7;
                border-radius: 8px;
                color: #7a8290;
                font-size: {base.SMALL_FONT_SIZE + 1}px;
                font-weight: bold;
            }}
            """
        )
        self.image_label.mouseDoubleClickEvent = self.open_current_image
        card_layout.addWidget(self.image_label, 0, Qt.AlignTop)

        self.info_layout = QVBoxLayout()
        self.info_layout.setSpacing(10)
        card_layout.addLayout(self.info_layout, 1)

        self.item_code_value = self.add_value_row("Item Code", multi_line=False)
        self.description_value = self.add_value_row("Description", multi_line=True)
        self.price_value = self.add_value_row("Price", multi_line=False)
        self.qty_row = self.add_group_row("Qty", ("W1", "W2", "W6", "Total Qty"))
        self.location_row = self.add_group_row("Location", ("Warehouse", "Showroom"))

        main_layout.addWidget(self.detail_card, 1)
        self.scan_input.setFocus()

    def configure_variant(self):
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)

    def eventFilter(self, watched, event):
        if watched is self.scan_input and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Tab:
            self.handle_lookup()
            return True
        return super().eventFilter(watched, event)

    def create_row_shell(self, content_height):
        row_frame = QFrame()
        row_frame.setStyleSheet(
            """
            QFrame {
                background-color: transparent;
                border: none;
            }
            """
        )
        row_layout = QHBoxLayout(row_frame)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        title_box = QLabel()
        title_box.setFixedWidth(LABEL_BOX_WIDTH)
        title_box.setFixedHeight(content_height)
        title_box.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        title_box.setStyleSheet(
            f"""
            QLabel {{
                background-color: #f7f9fc;
                border: 1px solid #dbe1eb;
                border-radius: 7px;
                padding: 0 10px;
                font-size: {TITLE_FONT_SIZE}px;
                font-weight: bold;
                color: #445066;
            }}
            """
        )
        row_layout.addWidget(title_box)

        content_box = QFrame()
        content_box.setFixedHeight(content_height)
        content_box.setStyleSheet(
            """
            QFrame {
                background-color: #fbfcfe;
                border: 1px solid #dbe1eb;
                border-radius: 7px;
            }
            """
        )
        row_layout.addWidget(content_box, 1)

        self.info_layout.addWidget(row_frame)
        return title_box, content_box

    def add_value_row(self, title, multi_line=False):
        content_height = MULTI_ROW_HEIGHT if multi_line else ROW_HEIGHT
        title_box, content_box = self.create_row_shell(content_height)
        title_box.setText(title)

        layout = QVBoxLayout(content_box)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(0)

        value_label = QLabel()
        value_label.setWordWrap(True)
        value_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_label.setStyleSheet(
            f"""
            QLabel {{
                background-color: transparent;
                border: none;
                padding: 0;
                font-size: {VALUE_FONT_SIZE}px;
                font-weight: bold;
                color: #111;
            }}
            """
        )
        layout.addWidget(value_label, 1)
        return value_label

    def add_group_row(self, title, keys):
        title_box, content_box = self.create_row_shell(ROW_HEIGHT)
        title_box.setText(title)

        layout = QHBoxLayout(content_box)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(8)

        chip_map = {}
        for key in keys:
            chip = QLabel()
            chip.setAlignment(Qt.AlignCenter)
            chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            chip.setStyleSheet(self.group_chip_style())
            layout.addWidget(chip)
            chip_map[key] = chip

        return chip_map

    def group_chip_style(self, background="#f7f9fc", border="#dbe1eb", text="#111"):
        return (
            "QLabel {"
            f"background-color: {background};"
            f"border: 1px solid {border};"
            "border-radius: 6px;"
            "padding: 2px 4px;"
            f"color: {text};"
            "}"
        )

    def handle_lookup(self):
        raw_value = self.scan_input.text().strip()
        if not raw_value:
            return

        value_list = self.parse_multi_input(raw_value)
        if not value_list:
            self.scan_input.clear()
            self.scan_input.setFocus()
            return

        lookup_value = value_list[0]

        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            row = self.query_one_upc(cursor, lookup_value)
            search_mode = "barcode"
            if row is None:
                row = self.query_one_item_code(cursor, lookup_value)
                search_mode = "item code"
            cursor.close()
            conn.close()
        except Exception as exc:
            QMessageBox.critical(self, "Database Error", str(exc))
            return

        if row is None:
            self.clear_detail_card()
            self.status_label.setText(f"Not found: {lookup_value}")
            self.scan_input.selectAll()
            self.scan_input.setFocus()
            return

        self.render_detail(row)
        self.status_label.setText(f"Showing 1 result for {search_mode}: {lookup_value}")
        self.scan_input.clear()
        self.scan_input.setFocus()

    def base_select_sql(self):
        whs_num = "LTRIM(RTRIM(CONVERT(VARCHAR(10), v.[WHS_NUM])))"
        available_qty = "(ISNULL(v.[IN_STOCK], 0) - ISNULL(v.[ORDER_QTY], 0))"
        wh1_location = "NULLIF(LTRIM(RTRIM(CONVERT(VARCHAR(100), v.[inv_loc]))), '')"

        return f"""
            SELECT
                i.[PROD_CD] AS [Item Code],
                i.[DESCRIP] AS [Description],
                i.[IMAGE_NM] AS [Image Name],
                i.[RETAIL_PRS] AS [Price],
                SUM(CASE WHEN {whs_num} = '1' THEN {available_qty} END) AS [WH1_QTY],
                MAX(CASE WHEN {whs_num} = '1' THEN {wh1_location} END) AS [WAREHOUSE],
                SUM(CASE WHEN {whs_num} = '2' THEN {available_qty} END) AS [WH2_QTY],
                SUM(CASE WHEN {whs_num} = '6' THEN {available_qty} END) AS [WH6_QTY],
                SUM(CASE WHEN {whs_num} IN ('1', '2', '6') THEN {available_qty} END) AS [TOTAL_QTY],
                i.[unit_color] AS [Showroom Location],
                i.[UNIT_NM] AS [Unit Name]
            FROM [omsdata].[dbo].[inv] i
            LEFT JOIN [omsdata].[dbo].[inv_data] v
                ON i.[PROD_CD] = v.[PROD_CD]
        """

    def query_one_upc(self, cursor, upc):
        query = self.base_select_sql() + """
            WHERE LTRIM(RTRIM(i.[UPC_CD])) = ?
            GROUP BY i.[PROD_CD], i.[DESCRIP], i.[IMAGE_NM], i.[RETAIL_PRS], i.[unit_color], i.[UNIT_NM]
        """

        candidates = []
        base_upc = str(upc).strip()
        if base_upc:
            candidates.append(base_upc)
        if len(base_upc) > 1:
            candidates.append(base_upc[:-1])
        if len(base_upc) > 2:
            candidates.append(base_upc[:-2])

        seen = set()
        unique_candidates = []
        for code in candidates:
            if code and code not in seen:
                unique_candidates.append(code)
                seen.add(code)

        for code in unique_candidates:
            cursor.execute(query, (code,))
            result = cursor.fetchone()
            if result is not None:
                return result

        return None

    def query_one_item_code(self, cursor, item_code):
        query = self.base_select_sql() + """
            WHERE LTRIM(RTRIM(i.[PROD_CD])) = ?
            GROUP BY i.[PROD_CD], i.[DESCRIP], i.[IMAGE_NM], i.[RETAIL_PRS], i.[unit_color], i.[UNIT_NM]
        """
        cursor.execute(query, (str(item_code).strip(),))
        return cursor.fetchone()

    def format_price_with_unit(self, price_value, unit_name):
        price_text = self.format_price(price_value)
        unit_text = self.normalize_text(unit_name)
        if price_text and unit_text:
            return f"{price_text} / {unit_text}"
        if price_text:
            return price_text
        return unit_text or "--"

    def reset_table(self):
        self.clear_detail_card()
        self.status_label.setText("Cleared. Ready for the next scan or search.")
        self.scan_input.clear()
        self.scan_input.setFocus()

    def clear_detail_card(self):
        self.current_image_path = None
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("No Image")
        self.item_code_value.setText("")
        self.description_value.setText("")
        self.price_value.setText("")

        for chip in self.qty_row.values():
            chip.setText("")
            chip.setStyleSheet(self.group_chip_style())

        for chip in self.location_row.values():
            chip.setText("")
            chip.setStyleSheet(self.group_chip_style())

    def render_detail(self, row):
        item_code = self.normalize_text(row[0])
        description = self.normalize_text(row[1])
        image_name = row[2]
        price = self.format_price_with_unit(row[3], row[10] if len(row) > 10 else "")
        wh1_qty_value = row[4]
        warehouse_loc = self.normalize_text(row[5])
        wh2_qty_value = row[6]
        wh6_qty_value = row[7]
        total_qty_value = row[8]
        showroom_loc = self.normalize_text(row[9])

        self.item_code_value.setText(item_code or "--")
        self.description_value.setText(self.format_description_for_display(description, width=34) or "--")
        self.price_value.setText(price or "--")

        self.set_group_chip(self.qty_row["W1"], "W1", wh1_qty_value)
        self.set_group_chip(self.qty_row["W2"], "W2", wh2_qty_value)
        self.set_group_chip(self.qty_row["W6"], "W6", wh6_qty_value)
        self.set_group_chip(self.qty_row["Total Qty"], "Total Qty", total_qty_value, highlight_total=True)

        self.set_text_chip(self.location_row["Warehouse"], "Warehouse", warehouse_loc)
        self.set_text_chip(self.location_row["Showroom"], "Showroom", showroom_loc)

        self.load_detail_image(image_name)

    def set_group_chip(self, chip, title, value, highlight_total=False):
        if value is None:
            display_value = "--"
            chip.setStyleSheet(self.group_chip_style(background="#eef1f5", border="#d6dbe5", text="#7a8290"))
        else:
            display_value = self.format_qty(value)
            if highlight_total and self.is_non_positive_qty(value):
                chip.setStyleSheet(self.group_chip_style(background="#ffdddd", border="#e19a9a", text="#8e1d1d"))
            else:
                chip.setStyleSheet(self.group_chip_style())

        chip.setText(
            f"<div style='font-size:{CHIP_TITLE_FONT_SIZE}px; font-weight:700;'>{title}</div>"
            f"<div style='font-size:{CHIP_VALUE_FONT_SIZE}px; font-weight:700;'>{display_value}</div>"
        )

    def set_text_chip(self, chip, title, value):
        display_value = value or "--"
        if value:
            chip.setStyleSheet(self.group_chip_style())
        else:
            chip.setStyleSheet(self.group_chip_style(background="#eef1f5", border="#d6dbe5", text="#7a8290"))

        chip.setText(
            f"<div style='font-size:{CHIP_TITLE_FONT_SIZE}px; font-weight:700;'>{title}</div>"
            f"<div style='font-size:{CHIP_VALUE_FONT_SIZE}px; font-weight:700;'>{display_value}</div>"
        )

    def resolve_image_path(self, image_name):
        if not image_name:
            return None

        image_name = str(image_name).strip()
        direct_path = os.path.join(IMAGE_DIR, image_name)
        if os.path.exists(direct_path):
            return direct_path

        stem, ext = os.path.splitext(image_name)
        if stem:
            matches = glob.glob(os.path.join(IMAGE_DIR, stem + ".*"))
            if matches:
                return matches[0]

        return None

    def load_detail_image(self, image_name):
        candidate_path = self.resolve_image_path(image_name)
        if candidate_path:
            pixmap = QPixmap(candidate_path)
            if not pixmap.isNull():
                if pixmap.height() > pixmap.width() * 1.2:
                    pixmap = pixmap.transformed(QTransform().rotate(90))
                scaled = pixmap.scaled(
                    self.image_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self.image_label.setPixmap(scaled)
                self.image_label.setText("")
                self.current_image_path = candidate_path
                return

        self.current_image_path = None
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText("No Image")

    def open_current_image(self, event):
        if self.current_image_path and os.path.exists(self.current_image_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_image_path))
        else:
            QMessageBox.information(self, "Info", "There is no image available for this item.")

    def print_table(self):
        return


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = InfoCheckinApp()
    window.show()
    sys.exit(app.exec_())
