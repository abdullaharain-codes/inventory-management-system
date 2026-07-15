"""Minimal test: which @page size formats does Chrome actually honor?"""
import asyncio
from playwright.async_api import async_playwright
from pypdf import PdfReader
from pathlib import Path

OUT = Path(r"C:\Users\Muhammad Abdullah\AppData\Local\Temp\opencode")

TESTS = [
    ("A: static @page { size: 80mm; }", '<style>@page { size: 80mm; margin: 2mm; }</style>'),
    ("B: static @page { size: 80mm 200mm; }", '<style>@page { size: 80mm 200mm; margin: 2mm; }</style>'),
    ("C: static @page { size: auto; }", '<style>@page { size: auto; margin: 2mm; }</style>'),
    ("D: static @page { size: A4; }", '<style>@page { size: A4; margin: 2mm; }</style>'),
    ("E: static @page { size: 80mm auto; }", '<style>@page { size: 80mm auto; margin: 2mm; }</style>'),
]

DYNAMIC_TESTS = [
    ("F: dynamic @page { size: 80mm; }", "@page { size: 80mm; margin: 2mm; }"),
    ("G: dynamic @page { size: 80mm auto; }", "@page { size: 80mm auto; margin: 2mm; }"),
    ("H: dynamic @page { size: 80mm 200mm; }", "@page { size: 80mm 200mm; margin: 2mm; }"),
]


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 800, "height": 600})

        for label, css in TESTS:
            page = await ctx.new_page()
            html = f"<html><head>{css}</head><body><p>{label}</p></body></html>"
            await page.set_content(html)
            rules = await page.evaluate("""() => {
                const r = [];
                for (const sheet of document.styleSheets) {
                    try { for (const rule of sheet.cssRules) {
                        if (rule.type === 6) r.push(rule.cssText);
                    }} catch(e) {}
                }
                return r;
            }""")
            pdf_path = OUT / f"pagegrid_{label[0].lower()}.pdf"
            await page.pdf(path=str(pdf_path), print_background=True, prefer_css_page_size=True)
            reader = PdfReader(str(pdf_path))
            box = reader.pages[0].mediabox
            w_mm = float(box.width) * 25.4 / 72
            h_mm = float(box.height) * 25.4 / 72
            print(f"{label}")
            print(f"  Parsed rules: {rules}")
            print(f"  PDF: {float(box.width):.1f} x {float(box.height):.1f} pts = {w_mm:.1f} x {h_mm:.1f} mm")
            print()
            await page.close()

        for label, css_text in DYNAMIC_TESTS:
            page = await ctx.new_page()
            await page.set_content(f"<html><body><p>{label}</p></body></html>")
            await page.evaluate(f"""() => {{
                const s = document.createElement('style');
                s.id = 'dynamicPrintStyle';
                s.textContent = '{css_text}';
                document.head.appendChild(s);
            }}""")
            rules = await page.evaluate("""() => {
                const r = [];
                for (const sheet of document.styleSheets) {
                    try { for (const rule of sheet.cssRules) {
                        if (rule.type === 6) r.push(rule.cssText);
                    }} catch(e) {}
                }
                return r;
            }""")
            pdf_path = OUT / f"pagegrid_{label[0].lower()}.pdf"
            await page.pdf(path=str(pdf_path), print_background=True, prefer_css_page_size=True)
            reader = PdfReader(str(pdf_path))
            box = reader.pages[0].mediabox
            w_mm = float(box.width) * 25.4 / 72
            h_mm = float(box.height) * 25.4 / 72
            print(f"{label}")
            print(f"  Parsed rules: {rules}")
            print(f"  PDF: {float(box.width):.1f} x {float(box.height):.1f} pts = {w_mm:.1f} x {h_mm:.1f} mm")
            print()
            await page.close()

        await browser.close()

asyncio.run(main())
