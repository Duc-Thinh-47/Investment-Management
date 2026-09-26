import pandas as pd
import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

# ============================================================
# CẤU HÌNH
# ============================================================
INPUT_XLSX  = "data/VN Index.xlsx"      # File xlsx hiện tại (dữ liệu CSV nằm ở ô A1)
OUTPUT_XLSX = "output.xlsx"     # File xlsx đầu ra (đã parse đúng cấu trúc)
SHEET_NAME  = "Dữ liệu Lịch sử VN Index"          # Tên sheet chứa dữ liệu
CELL_REF    = "A1"              # Ô chứa chuỗi CSV

# ============================================================
# BƯỚC 1: Đọc nội dung CSV từ ô A1 của file xlsx
# ============================================================
wb = Workbook()  # chỉ để mở file cũ, ta dùng openpyxl trực tiếp
from openpyxl import load_workbook

src_wb = load_workbook(INPUT_XLSX, read_only=True)
ws     = src_wb[SHEET_NAME]

csv_text = ws[CELL_REF].value
src_wb.close()

print(f"✅ Đã đọc {len(csv_text)} ký tự từ ô {CELL_REF}")
print(f"Preview: {csv_text[:120]}...")

# ============================================================
# BƯỚC 2: Parse chuỗi CSV thành DataFrame
# ============================================================
# Dùng io.StringIO để giả lập file CSV từ chuỗi text
df = pd.read_csv(io.StringIO(csv_text), sep=",")

# Đổi tên cột cho sạch (bỏ dấu ngoặc kép nếu còn)
df.columns = [col.strip().strip('"') for col in df.columns]

print(f"\n✅ Đã parse thành DataFrame: {df.shape[0]} dòng x {df.shape[1]} cột")
print(df.head())

# ============================================================
# BƯỚC 3: Xuất ra file XLSX có định dạng đẹp
# ============================================================
out_wb = Workbook()
out_ws = out_wb.active
out_ws.title = "Stock Data"

# --- Style định nghĩa ---
header_font   = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
header_fill   = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
header_align  = Alignment(horizontal="center", vertical="center", wrap_text=True)
cell_font     = Font(name="Calibri", size=11)
thin_border   = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

# --- Ghi Header ---
for col_idx, col_name in enumerate(df.columns, start=1):
    cell = out_ws.cell(row=1, column=col_idx, value=col_name)
    cell.font       = header_font
    cell.fill       = header_fill
    cell.alignment  = header_align
    cell.border     = thin_border

# --- Ghi Data ---
for row_idx, row in enumerate(df.itertuples(index=False), start=2):
    for col_idx, value in enumerate(row, start=1):
        cell = out_ws.cell(row=row_idx, column=col_idx, value=value)
        cell.font   = cell_font
        cell.border = thin_border

        # Căn phải cho cột số (KL, % Thay đổi, giá)
        if col_idx > 1:
            cell.alignment = Alignment(horizontal="right")

# --- Auto-fit column width ---
for col_idx, col_name in enumerate(df.columns, start=1):
    max_len = max(
        len(str(col_name)),
        df.iloc[:, col_idx - 1].astype(str).str.len().max()
    )
    adjusted_width = min(max_len + 4, 40)  # cap ở 40 ký tự
    out_ws.column_dimensions[get_column_letter(col_idx)].width = adjusted_width

# --- Freeze pane (cố định header) ---
out_ws.freeze_panes = "A2"

# --- Auto-filter ---
out_ws.auto_filter.ref = out_ws.dimensions

# Lưu file
out_wb.save(OUTPUT_XLSX)
print(f"\n🎉 Đã xuất file: {OUTPUT_XLSX}")
print(f"   Kích thước: {df.shape[0]} dòng dữ liệu + 1 dòng header")