import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://korido.hu"
RESULT = BASE + "/2026EMU6_result?rc=3600&tbl=1"
OUT = Path("data/athletes.json")


def clean(value):
    return " ".join((value or "").split())


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1600, "height": 1400},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
            ),
        )

        page.goto(RESULT, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(10000)

        # The individual-results table is rendered client-side. In the live
        # page the athlete name is not necessarily an <a>, so do not depend on
        # resultTableLaps.php links being present.
        rows = page.locator("table tbody tr")
        count = rows.count()

        # If the table is paginated by DataTables, temporarily switch it to
        # show all rows. This is intentionally done in the browser because the
        # page's data source is client-side.
        try:
            page.evaluate(
                """
                () => {
                    if (window.jQuery && jQuery.fn && jQuery.fn.dataTable) {
                        jQuery.fn.dataTable.tables({api: true}).each(function() {
                            try { this.page.len(-1).draw(false); } catch (e) {}
                        });
                    }
                }
                """
            )
            page.wait_for_timeout(3000)
            count = rows.count()
        except Exception:
            pass

        records = rows.evaluate_all(
            """
            trs => trs.map(tr => {
                const cells = Array.from(tr.querySelectorAll('td'))
                    .map(td => (td.innerText || '').trim());
                return cells;
            })
            """
        )

        # If DataTables pagination is still active, collect the visible pages
        # by clicking its Next button until it becomes disabled.
        seen_pages = set()
        def collect_page():
            current = rows.evaluate_all(
                "trs => trs.map(tr => Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').trim()))"
            )
            return current

        all_rows = list(records)
        for _ in range(30):
            page_key = "\n".join("|".join(r) for r in collect_page())
            if page_key in seen_pages:
                break
            seen_pages.add(page_key)

            next_buttons = page.locator(
                ".dataTables_paginate .next, .paginate_button.next, "
                "button[aria-label*='Next'], a[aria-label*='Next']"
            )
            if next_buttons.count() == 0:
                break
            nxt = next_buttons.first
            cls = (nxt.get_attribute("class") or "").lower()
            disabled = nxt.is_disabled() if nxt.evaluate("el => 'disabled' in el") else False
            if disabled or "disabled" in cls:
                break
            try:
                nxt.click(timeout=3000)
                page.wait_for_timeout(500)
            except Exception:
                break
            all_rows.extend(collect_page())

        if not all_rows:
            title = page.title()
            body = clean(page.locator("body").inner_text())[:6000]
            print(f"Discovery diagnostics: title={title!r}, table_rows={count}")
            print(body)
            browser.close()
            raise RuntimeError("No rendered athlete rows were found on the Köridő individual-results page.")

        browser.close()

    by_bib = {}
    bib_re = re.compile(r"^(?:\d+|[A-Za-z]+\d+)$")

    for cells in all_rows:
        if len(cells) < 5:
            continue

        # Current header order is: Pos, Category pos, age-group pos,
        # Bibnumber, Name, Country, Category, ... . Find the bib rather than
        # relying on a hard-coded column index.
        bib_index = None
        for i, value in enumerate(cells[:8]):
            if bib_re.fullmatch(clean(value)):
                bib_index = i
                break
        if bib_index is None or bib_index + 1 >= len(cells):
            continue

        bib = clean(cells[bib_index])
        name = clean(cells[bib_index + 1])
        if not name or name.lower() in {"name", "country"}:
            continue

        country = clean(cells[bib_index + 2]) if bib_index + 2 < len(cells) else ""
        category = clean(cells[bib_index + 3]) if bib_index + 3 < len(cells) else ""

        by_bib[bib] = {
            "bib": bib,
            "name": name,
            "country": country,
            "category": category,
        }

    athletes = list(by_bib.values())
    athletes.sort(key=lambda x: x["bib"])

    # The official race information reported 108 starters. Do not overwrite
    # the stored discovery list with a partial table.
    if len(athletes) < 100:
        raise RuntimeError(
            f"Discovery returned only {len(athletes)} athletes; refusing to save an incomplete list"
        )

    with OUT.open("w", encoding="utf-8") as f:
        json.dump(athletes, f, ensure_ascii=False, indent=2)

    print(f"Discovered {len(athletes)} athletes")


if __name__ == "__main__":
    main()
