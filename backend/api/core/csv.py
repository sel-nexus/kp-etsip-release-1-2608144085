"""Serialize fixed report columns without modifying stored values."""
import csv
from io import StringIO
from collections.abc import Mapping, Sequence

def safe_cell(value: object) -> str:
    """Normalize nulls and neutralize spreadsheet formulas before quoting."""
    text = '' if value is None else str(value)
    return "'" + text if text.startswith(('=', '+', '-', '@')) else text

def csv_line(columns: Sequence[str], row: Mapping[str, object] | None = None) -> bytes:
    """Encode one properly quoted UTF-8 header or fixed-column data row."""
    output = StringIO(newline='')
    csv.writer(output, lineterminator='\r\n').writerow(columns if row is None else [safe_cell(row.get(column)) for column in columns])
    return output.getvalue().encode('utf-8')
