"""Verification test for the @page size fix (V3) — dynamic height computation."""
import asyncio, sys, os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright
from pypdf import PdfReader

BASE = "http://127.0.0.1:5000"
OUT = Path(r"C:\Users\Muhammad Abdullah\AppData\Local\Temp\opencode")
OUT.mkdir(parents=True, exist_ok=True)

EMAIL = "admin@test.com"
PASSWORD = "Admin@123"


def mm(pts):
    return pts * 25.4 / 72


def report(label, path):
    r = PdfReader(str(path))
    for i, p in enumerate(r.pages):
        b = p.mediabox
        print(f"  {label} p{i+1}: {float(b.width):.1f} x {float(b.height):.1f} pts = {mm(float(b.width)):.1f} x {mm(float(b.height)):.1f} mm")
    txt = "".join((p.extract_text() or "") for p in r.pages)
    print(f"  {label} text: {len(txt)} chars — {txt[:100]}...")
    return r


async def main():
    print("=" * 70)
    print("VERIFICATION: @page dynamic height (V3)")
    print("=" * 70)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()

        # Login
        print("\n--- LOGIN ---")
        await page.goto(BASE + "/", wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
        r = await page.evaluate("""async () => {
            const r = await fetch('/api/auth/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({email: '""" + EMAIL + """', password: '""" + PASSWORD + """'})
            });
            return {status: r.status, body: await r.json()};
        }""")
        print(f"  {r['status']}: {r['body'].get('message', r['body'].get('error', '???'))}")
        if r["status"] != 200:
            print("  FATAL"); return

        # Get bills
        bills = await page.evaluate("async () => fetch('/api/bills').then(r=>r.json())")
        if not bills:
            print("  FATAL: no bills"); return
        bill_id = bills[0]["bill_id"]
        print(f"  Bill: {bills[0].get('bill_number')} (id={bill_id})")

        # Set thermal
        await page.evaluate("""async () => {
            await fetch('/api/company-info', {
                method:'PUT', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({invoice_format:'thermal_80mm'})
            });
        }""")

        # ── TEST 1: billing.html thermal ──────────────────────────
        print("\n--- TEST 1: billing.html thermal ---")
        await page.goto(BASE + "/billing", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Call applyPrintPageSize directly with a measured height
        result = await page.evaluate("""async (billId) => {
            // Fetch bill + company info
            const bill = await fetch('/api/bills/' + billId).then(r => r.json());
            const company = await fetch('/api/company-info').then(r => r.json());
            const fmt = company.invoice_format || 'a4';

            // Set receipt content (replicate showReceipt)
            var body = document.getElementById('receiptBody');
            body.innerHTML = '<div style="font-family:monospace;font-size:13px;"><h2>TEST RECEIPT</h2><p>Bill: ' + bill.bill_number + '</p><p>Item A x2</p><p>Item B x1</p><p>Item C x3</p><p>TOTAL: PKR 15,000</p></div>';

            // Show overlay
            document.getElementById('printOverlay').style.display = 'flex';

            // Toggle thermal class
            var pm = document.querySelector('.print-modal');
            if (pm) pm.classList.add('receipt-thermal');

            // Measure at thermal width
            var origW = pm.style.width;
            pm.style.width = '76mm';
            void pm.offsetHeight;
            var measured = body.scrollHeight;
            pm.style.width = origW;

            // Call applyPrintPageSize with height
            applyPrintPageSize(fmt, measured);

            return {
                format: fmt,
                measuredPx: measured,
                styleText: document.getElementById('dynamicPrintStyle')?.textContent || 'N/A'
            };
        }""", bill_id)
        print(f"  {result}")

        pdf1 = OUT / "verify_billing_thermal.pdf"
        await page.emulate_media(media="print")
        await page.wait_for_timeout(500)
        await page.pdf(path=str(pdf1), print_background=True, prefer_css_page_size=True)
        await page.emulate_media(media="screen")
        report("BILLING-THERMAL", pdf1)

        # ── TEST 2: billing.html thermal with MORE content ────────
        print("\n--- TEST 2: billing.html thermal — MORE items ---")
        await page.goto(BASE + "/billing", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        result2 = await page.evaluate("""(billId) => {
            var body = document.getElementById('receiptBody');
            var items = '';
            for (var i = 1; i <= 15; i++) {
                items += '<div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px;"><span>Item ' + i + ' x' + (i % 3 + 1) + '</span><span>PKR ' + (i * 500) + '</span></div>';
            }
            body.innerHTML = '<div style="font-family:monospace;font-size:13px;padding:16px;">' +
                '<h2>TEST RECEIPT — 15 ITEMS</h2>' + items +
                '<hr style="margin:8px 0;border-top:1px dashed #ccc;">' +
                '<div style="font-size:16px;font-weight:bold;text-align:right;">TOTAL: PKR 60,000</div></div>';

            document.getElementById('printOverlay').style.display = 'flex';
            var pm = document.querySelector('.print-modal');
            if (pm) pm.classList.add('receipt-thermal');

            var origW = pm.style.width;
            pm.style.width = '76mm';
            void pm.offsetHeight;
            var measured = body.scrollHeight;
            pm.style.width = origW;

            applyPrintPageSize('thermal_80mm', measured);

            return {measuredPx: measured, styleText: document.getElementById('dynamicPrintStyle')?.textContent};
        }""", bill_id)
        print(f"  {result2}")

        pdf2 = OUT / "verify_billing_thermal_many.pdf"
        await page.emulate_media(media="print")
        await page.wait_for_timeout(500)
        await page.pdf(path=str(pdf2), print_background=True, prefer_css_page_size=True)
        await page.emulate_media(media="screen")
        report("BILLING-THERMAL-15ITEMS", pdf2)

        # ── TEST 3: bill_history.html thermal ─────────────────────
        print("\n--- TEST 3: bill_history.html thermal ---")
        await page.goto(BASE + "/bill-history", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        await page.evaluate(f"openDetail({bill_id})")
        await page.wait_for_timeout(3000)

        # Check console logs
        logs = await page.evaluate("""() => {
            return window.__printLogs || [];
        }""")
        print(f"  Console logs captured: {logs}")

        pdf3 = OUT / "verify_billhistory_thermal.pdf"
        await page.emulate_media(media="print")
        await page.wait_for_timeout(500)
        await page.pdf(path=str(pdf3), print_background=True, prefer_css_page_size=True)
        await page.emulate_media(media="screen")
        report("BILLHISTORY-THERMAL", pdf3)

        # ── TEST 4: A4 comparison ─────────────────────────────────
        print("\n--- TEST 4: billing.html A4 ---")
        await page.evaluate("""async () => {
            await fetch('/api/company-info', {
                method:'PUT', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({invoice_format:'a4'})
            });
        }""")
        await page.goto(BASE + "/billing", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        await page.evaluate("""() => {
            var body = document.getElementById('receiptBody');
            body.innerHTML = '<div style="font-family:monospace;font-size:13px;padding:20px;"><h1>A4 TEST</h1><p>Standard A4 receipt</p></div>';
            document.getElementById('printOverlay').style.display = 'flex';
            var pm = document.querySelector('.print-modal');
            if (pm) pm.classList.remove('receipt-thermal');
            applyPrintPageSize('a4');
        }""")

        pdf4 = OUT / "verify_billing_a4.pdf"
        await page.emulate_media(media="print")
        await page.wait_for_timeout(500)
        await page.pdf(path=str(pdf4), print_background=True, prefer_css_page_size=True)
        await page.emulate_media(media="screen")
        report("BILLING-A4", pdf4)

        # Reset to thermal
        await page.evaluate("""async () => {
            await fetch('/api/company-info', {
                method:'PUT', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({invoice_format:'thermal_80mm'})
            });
        }""")

        print("\n" + "=" * 70)
        print("VERIFICATION COMPLETE")
        print("=" * 70)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
