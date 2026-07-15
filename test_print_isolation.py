"""
Isolation test for print issues — uses Playwright headless Chromium + page.pdf()
to bypass OS print dialog and any printer driver entirely.

ISSUE 1: Does Chrome headless honor the dynamically-injected @page { size: 80mm } rule?
ISSUE 2: Is #detailOverlay visible under print media after the CSS specificity fix?
"""
import asyncio, sys, os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright
from pypdf import PdfReader

BASE = "http://127.0.0.1:5000"
OUT_DIR = Path(r"C:\Users\Muhammad Abdullah\AppData\Local\Temp\opencode")
OUT_DIR.mkdir(parents=True, exist_ok=True)

EMAIL = "admin@test.com"
PASSWORD = "Admin@123"


def mm_from_points(pts):
    return pts * 25.4 / 72


def report_pdf(label, pdf_path):
    if not pdf_path.exists():
        print(f"  {label}: PDF NOT FOUND")
        return None
    reader = PdfReader(str(pdf_path))
    for i, p in enumerate(reader.pages):
        box = p.mediabox
        w_mm = mm_from_points(float(box.width))
        h_mm = mm_from_points(float(box.height))
        print(f"  {label} Page {i+1}: {float(box.width):.1f} x {float(box.height):.1f} pts = {w_mm:.1f} x {h_mm:.1f} mm")
    total_text = ""
    for p in reader.pages:
        total_text += (p.extract_text() or "")
    print(f"  {label} Text length: {len(total_text)} chars")
    if total_text:
        print(f"  {label} Text preview: {total_text[:120]}...")
    return reader


async def main():
    print("="*70)
    print("PRINT ISOLATION TEST SUITE")
    print(f"Output: {OUT_DIR}")
    print("="*70)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        # ── LOGIN ──────────────────────────────────────────────────
        print("\n--- LOGIN ---")
        await page.goto(BASE + "/", wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
        resp = await page.evaluate("""async () => {
            const r = await fetch('/api/auth/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({email: '""" + EMAIL + """', password: '""" + PASSWORD + """'})
            });
            return {status: r.status, body: await r.json()};
        }""")
        print(f"  Login: {resp['status']} — {resp['body'].get('message', resp['body'].get('error', '???'))}")
        if resp["status"] != 200:
            print("  FATAL: Login failed"); return

        # ── GET BILLS ──────────────────────────────────────────────
        bills = await page.evaluate("async () => { const r = await fetch('/api/bills'); return r.json(); }")
        if not bills:
            print("  FATAL: No bills in DB"); return
        bill_id = bills[0]["bill_id"]
        print(f"  Bill: {bills[0].get('bill_number', '?')} (id={bill_id})")

        # ══════════════════════════════════════════════════════════════
        # ISSUE 1: THERMAL @page TEST
        # ══════════════════════════════════════════════════════════════
        print("\n" + "="*70)
        print("ISSUE 1: THERMAL @page — headless Chrome print-to-PDF")
        print("="*70)

        # Set thermal format
        print("\n[1] Setting invoice_format=thermal_80mm...")
        await page.evaluate("""async () => {
            await fetch('/api/company-info', {
                method: 'PUT', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({invoice_format: 'thermal_80mm'})
            });
        }""")

        # Navigate to billing
        print("[2] Navigating to /billing...")
        await page.goto(BASE + "/billing", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Call applyPrintPageSize directly (it's global from base.html)
        print("[3] Calling applyPrintPageSize('thermal_80mm') directly...")
        result = await page.evaluate("""() => {
            if (typeof applyPrintPageSize !== 'function') return {error: 'applyPrintPageSize not found'};
            applyPrintPageSize('thermal_80mm');
            var el = document.getElementById('dynamicPrintStyle');
            var pm = document.querySelector('.print-modal');
            if (pm) pm.classList.add('receipt-thermal');
            return {
                ok: true,
                styleText: el ? el.textContent : 'N/A',
                styleExists: !!el,
                thermalClass: pm ? pm.classList.contains('receipt-thermal') : false
            };
        }""")
        print(f"  Result: {result}")

        # List ALL @page rules currently in DOM
        print("[4] Listing all @page rules in DOM...")
        page_rules = await page.evaluate("""() => {
            const results = [];
            for (const sheet of document.styleSheets) {
                try {
                    const walk = (rules, depth) => {
                        for (const rule of rules) {
                            if (rule.type === 4) { // MEDIA_RULE
                                if (window.matchMedia(rule.conditionText).matches) {
                                    walk(rule.cssRules, depth + 1);
                                }
                            } else if (rule.type === 6) { // PAGE_RULE
                                results.push({
                                    text: rule.cssText,
                                    href: sheet.href || '(inline)',
                                    depth: depth
                                });
                            }
                        }
                    };
                    walk(sheet.cssRules, 0);
                } catch(e) { results.push({error: e.message, href: sheet.href || '(inline)'}); }
            }
            return results;
        }""")
        for r in page_rules:
            print(f"  {r}")

        # Show the overlay so page.pdf() has content to print
        print("[5] Showing printOverlay with receipt content...")
        await page.evaluate("""() => {
            var body = document.getElementById('receiptBody');
            if (body) {
                body.innerHTML = '<div style="font-family:monospace;font-size:13px;padding:20px;"><h2>TEST RECEIPT</h2><p>Bill: TEST-001</p><p>Item: Widget x2 - $10.00</p><p>TOTAL: $20.00</p></div>';
            }
            var overlay = document.getElementById('printOverlay');
            if (overlay) overlay.style.display = 'flex';
        }""")
        await page.wait_for_timeout(500)

        # Emulate print media and check @page
        print("[6] Emulating print media...")
        await page.emulate_media(media="print")
        await page.wait_for_timeout(500)

        # Re-check @page rules under print media
        page_rules_print = await page.evaluate("""() => {
            const results = [];
            for (const sheet of document.styleSheets) {
                try {
                    const walk = (rules, depth) => {
                        for (const rule of rules) {
                            if (rule.type === 4) { // MEDIA_RULE
                                const matches = window.matchMedia(rule.conditionText).matches;
                                results.push({
                                    type: 'media',
                                    condition: rule.conditionText,
                                    matches: matches,
                                    childCount: rule.cssRules.length,
                                    href: sheet.href || '(inline)'
                                });
                                if (matches) walk(rule.cssRules, depth + 1);
                            } else if (rule.type === 6) { // PAGE_RULE
                                results.push({
                                    type: 'page',
                                    text: rule.cssText,
                                    href: sheet.href || '(inline)',
                                    depth: depth
                                });
                            }
                        }
                    };
                    walk(sheet.cssRules, 0);
                } catch(e) {}
            }
            return results;
        }""")
        print("  CSS rules under print media:")
        for r in page_rules_print:
            print(f"    {r}")

        # Generate PDF — THIS IS THE CRITICAL TEST
        print("[7] Generating PDF via page.pdf(prefer_css_page_size=True)...")
        pdf_path = OUT_DIR / "issue1_thermal.pdf"
        try:
            await page.pdf(path=str(pdf_path), print_background=True, prefer_css_page_size=True)
            print(f"  Saved: {pdf_path}")
            report_pdf("THERMAL", pdf_path)
        except Exception as e:
            print(f"  ERROR: {e}")

        # COLD PRINT TEST — fresh page load, first print
        print("\n[8] COLD PRINT TEST — fresh load, first @page injection...")
        await page.emulate_media(media="screen")
        await page.goto(BASE + "/billing", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await page.evaluate("""() => {
            applyPrintPageSize('thermal_80mm');
            var pm = document.querySelector('.print-modal');
            if (pm) pm.classList.add('receipt-thermal');
            var body = document.getElementById('receiptBody');
            if (body) body.innerHTML = '<div style="padding:20px;"><h2>COLD TEST</h2></div>';
            var overlay = document.getElementById('printOverlay');
            if (overlay) overlay.style.display = 'flex';
        }""")
        cold_pdf = OUT_DIR / "issue1_thermal_cold.pdf"
        await page.emulate_media(media="print")
        await page.wait_for_timeout(500)
        try:
            await page.pdf(path=str(cold_pdf), print_background=True, prefer_css_page_size=True)
            print(f"  Cold PDF saved: {cold_pdf}")
            report_pdf("COLD", cold_pdf)
        except Exception as e:
            print(f"  Cold PDF ERROR: {e}")

        # A4 COMPARISON
        print("\n[9] A4 COMPARISON...")
        await page.emulate_media(media="screen")
        await page.goto(BASE + "/billing", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await page.evaluate("""() => {
            applyPrintPageSize('a4');
            var pm = document.querySelector('.print-modal');
            if (pm) pm.classList.remove('receipt-thermal');
            var body = document.getElementById('receiptBody');
            if (body) body.innerHTML = '<div style="padding:20px;"><h2>A4 TEST</h2></div>';
            var overlay = document.getElementById('printOverlay');
            if (overlay) overlay.style.display = 'flex';
        }""")
        a4_pdf = OUT_DIR / "issue1_a4.pdf"
        await page.emulate_media(media="print")
        await page.wait_for_timeout(500)
        try:
            await page.pdf(path=str(a4_pdf), print_background=True, prefer_css_page_size=True)
            report_pdf("A4", a4_pdf)
        except Exception as e:
            print(f"  A4 PDF ERROR: {e}")

        # ══════════════════════════════════════════════════════════════
        # ISSUE 2: BILL HISTORY BLANK PAGE TEST
        # ══════════════════════════════════════════════════════════════
        print("\n" + "="*70)
        print("ISSUE 2: BILL HISTORY — #detailOverlay in print media")
        print("="*70)

        await page.emulate_media(media="screen")
        print("\n[1] Navigating to /bill-history...")
        await page.goto(BASE + "/bill-history", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        print("[2] Opening bill detail via openDetail()...")
        await page.evaluate(f"openDetail({bill_id})")
        await page.wait_for_timeout(3000)

        print("[3] Checking #detailBody content...")
        body_info = await page.evaluate("""() => {
            const body = document.getElementById('detailBody');
            const overlay = document.getElementById('detailOverlay');
            return {
                bodyExists: !!body,
                htmlLen: body ? body.innerHTML.length : 0,
                htmlPreview: body ? body.innerHTML.substring(0, 300) : '',
                overlayDisplay: overlay ? overlay.style.display : 'N/A',
                overlayHasDetailOverlay: overlay ? overlay.id === 'detailOverlay' : false
            };
        }""")
        print(f"  detailBody exists: {body_info['bodyExists']}")
        print(f"  HTML length: {body_info['htmlLen']}")
        print(f"  HTML preview: {body_info['htmlPreview'][:200]}...")
        print(f"  overlay display: {body_info['overlayDisplay']}")

        if body_info['htmlLen'] == 0:
            print("  WARNING: detailBody is EMPTY")

        print("[4] Checking receipt-thermal class...")
        thermal_els = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('.receipt-thermal')).map(el => ({
                tag: el.tagName, id: el.id, class: el.className,
                parent: el.parentElement ? el.parentElement.id : ''
            }));
        }""")
        print(f"  receipt-thermal elements: {len(thermal_els)}")
        for t in thermal_els:
            print(f"    <{t['tag']} id='{t['id']}' class='{t['class']}'> (parent: {t['parent']})")

        print("[5] Emulating print media — checking computed styles...")
        await page.emulate_media(media="print")
        await page.wait_for_timeout(500)

        computed = await page.evaluate("""() => {
            const ids = ['detailOverlay'];
            const results = {};
            for (const id of ids) {
                const el = document.getElementById(id);
                if (!el) { results[id] = {exists: false}; continue; }
                const s = window.getComputedStyle(el);
                results[id] = {
                    exists: true, display: s.display, visibility: s.visibility,
                    opacity: s.opacity, height: s.height, width: s.width,
                    position: s.position, overflow: s.overflow
                };
            }
            const card = document.querySelector('#detailOverlay > div');
            if (card) {
                const s = window.getComputedStyle(card);
                results['card'] = {
                    display: s.display, visibility: s.visibility, height: s.height,
                    width: s.width, maxHeight: s.maxHeight, overflow: s.overflow
                };
            }
            const detailBody = document.getElementById('detailBody');
            if (detailBody) {
                const s = window.getComputedStyle(detailBody);
                results['detailBody'] = {
                    display: s.display, visibility: s.visibility, height: s.height,
                    width: s.width, overflow: s.overflow
                };
            }
            return results;
        }""")

        for name, styles in computed.items():
            print(f"\n  {name}:")
            if not styles.get("exists", True):
                print("    DOES NOT EXIST")
                continue
            for k, v in styles.items():
                flag = ""
                if k == "display" and v == "none": flag = " *** HIDDEN ***"
                if k == "visibility" and v == "hidden": flag = " *** INVISIBLE ***"
                if k == "opacity" and v == "0": flag = " *** TRANSPARENT ***"
                if k == "height" and v == "0px": flag = " *** ZERO ***"
                print(f"    {k}: {v}{flag}")

        # Check what CSS rules match #detailOverlay in print media
        print("\n[6] CSS rules matching #detailOverlay in print media:")
        rules = await page.evaluate("""() => {
            const overlay = document.getElementById('detailOverlay');
            if (!overlay) return [];
            const results = [];
            for (const sheet of document.styleSheets) {
                try {
                    for (const rule of sheet.cssRules) {
                        if (rule.type === 4) { // MEDIA_RULE
                            if (window.matchMedia(rule.conditionText).matches) {
                                for (const inner of rule.cssRules) {
                                    if (inner.selectorText && overlay.matches(inner.selectorText)) {
                                        results.push({
                                            media: rule.conditionText,
                                            selector: inner.selectorText,
                                            prop: inner.style.cssText.substring(0, 200),
                                            src: sheet.href || 'inline'
                                        });
                                    }
                                }
                            }
                        } else if (rule.selectorText && overlay.matches(rule.selectorText)) {
                            results.push({
                                media: 'all',
                                selector: rule.selectorText,
                                prop: rule.style.cssText.substring(0, 200),
                                src: sheet.href || 'inline'
                            });
                        }
                    }
                } catch(e) {}
            }
            return results;
        }""")
        for r in rules:
            print(f"  [{r['media']}] {r['selector']} {{ {r['prop']} }} (from {r['src']})")

        # Generate bill_history PDF
        print("\n[7] Generating bill_history print-to-PDF...")
        pdf_path2 = OUT_DIR / "issue2_bill_history.pdf"
        try:
            await page.pdf(path=str(pdf_path2), print_background=True, prefer_css_page_size=True)
            print(f"  Saved: {pdf_path2}")
            report_pdf("BILL_HISTORY", pdf_path2)
        except Exception as e:
            print(f"  ERROR: {e}")

        print("\n" + "="*70)
        print("ALL TESTS COMPLETE")
        print("="*70)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
