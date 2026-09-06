import json
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://korido.hu"
RESULT = BASE + "/2026EMU6_result?rc=3600&tbl=1"
OUT = Path("data/athletes.json")


def clean(value):
    return " ".join((value or "").split())


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(RESULT, wait_until="domcontentloaded", timeout=60000)

        selector = "a[href*='resultTableLaps.php?bib=']"
        page.wait_for_function(
            "selector => document.querySelectorAll(selector).length > 0",
            arg=selector,
            timeout=60000,
        )

        records = page.locator(selector).evaluate_all(
            """
            links => links.map(a => {
                const href = a.getAttribute('href') || '';
                // Bibs are not necessarily numeric: the live table contains
                // values such as 977, 1211 and W21.
                const m = href.match(/resultTableLaps\\.php\\?bib=([^&#]+)/);
                const row = a.closest('tr');
                const cells = row ? Array.from(row.querySelectorAll('td')).map(x => (x.innerText || '').trim()) : [];
                return {
                    bib: m ? decodeURIComponent(m[1]) : null,
                    name: (a.innerText || '').trim(),
                    country: cells.length > 6 ? cells[6] : '',
                    category: cells.length > 7 ? cells[7] : ''
                };
            })
            """
        )
        browser.close()

    by_bib = {}
    for item in records:
        bib = clean(item.get("bib"))
        if not bib:
            continue
        by_bib[bib] = {
            "bib": bib,
            "name": clean(item.get("name")),
            "country": clean(item.get("country")),
            "category": clean(item.get("category")),
        }

    athletes = sorted(by_bib.values(), key=lambda x: x["bib"])
    if len(athletes) < 50:
        raise RuntimeError(
            f"Discovery returned only {len(athletes)} athletes; refusing to save an incomplete list"
        )

    with OUT.open("w", encoding="utf-8") as f:
        json.dump(athletes, f, ensure_ascii=False, indent=2)

    print(f"Discovered {len(athletes)} athletes")


if __name__ == "__main__":
    main()
