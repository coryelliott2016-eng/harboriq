#!/usr/bin/env python3
"""Convert the plain-text copyright deposit listing into a paginated PDF
using a monospace font, so line breaks/indentation in the source code are
preserved exactly. Usage: python scripts/txt_to_pdf.py <in.txt> <out.pdf>
"""
import sys

from fpdf import FPDF

def main(in_path: str, out_path: str) -> None:
    with open(in_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    # Normalize characters outside latin-1 (core Courier font encoding) so
    # fpdf2 doesn't raise -- typographic dashes/quotes are cosmetic only.
    replacements = {
        "\u2014": "--", "\u2013": "-", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2026": "...",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    text = text.encode("latin-1", errors="replace").decode("latin-1")

    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    pdf.set_font("Courier", size=8)

    max_chars = 110
    for raw_line in text.splitlines():
        line = raw_line if raw_line else " "
        while len(line) > max_chars:
            pdf.cell(0, 3.6, line[:max_chars], ln=1)
            line = line[max_chars:]
        pdf.cell(0, 3.6, line, ln=1)

    pdf.output(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
