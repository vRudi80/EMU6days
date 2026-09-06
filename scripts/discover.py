import json
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://korido.hu"
# This is the live individual-results view that is visible in a normal browser.
RESULT = BASE + "/2026EMU6_result?team=1"
OUT = Path("data/athletes.json")


def clean(value):
    return " ".join((value or "").split())


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
            ),
        )

        # The result table is populated client-side, so give the page time to
        # finish its own JavaScript update cycle. Do not depend on a fragile
        # wait_for_function signature or on a specific pagination state.
        page.goto(RESULT, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(10000)

        selector = "a[href*='resultTableLaps.php']"
        count = page.locator(selector).count()

        # One reload helps when the live timing page initially renders before
        # its table data request has completed.
        if count == 0:
            page.reload(wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(10000)
            count = page.locator(selector).count()

        if count == 0:
            # Fail with useful diagnostics rather than silently producing an
            # incomplete athlete list.
            title = page.title()
            body = clean(page.locator("body").inner_text())[:4000]
            print(f"Discovery diagnostics: title={title!r}, links={count}")
            print(body)
            raise RuntimeError(
                "No athlete lap links were rendered by the Köridő page. "
                "The live result table may be temporarily unavailable."
            )

        records = page.locator(selector).evaluate_all(
            """
            links => links.map(a => {
                const href = a.getAttribute('href') || '';
                const m = href.match(/resultTableLaps\\.php\\?bib=([^&#]+)/);
                const row = a.closest('tr');
                const cells = row ? Array.from(row.querySelectorAll('td')).map(x => (x.innerText || '').trim()) : [];
                const nameCell = a.closest('td');
                const nameIndex = nameCell && row ? Array.from(row.querySelectorAll('td')).indexOf(nameCell) : -1;
                return {
                    bib: m ? decodeURIComponent(m[1]) : null,
                    name: (a.innerText || '').trim(),
                    country: nameIndex >= 0 && cells[nameIndex + 1] ? cells[nameIndex + 1] : '',
                    category: nameIndex >= 0 && cells[nameIndex + 2] ? cells[nameIndex + 2] : ''
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
