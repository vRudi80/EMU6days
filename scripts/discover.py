import json
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://korido.hu"
RESULT = BASE + "/2026EMU6_result?rc=3600&tbl=1"
OUT = Path("data/athletes.json")


def clean(value):
    return " ".join((value or "").split())


def norm(value):
    return clean(value).lower().replace(" ", "")


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

        # Locate the actual individual-results table by its column headers.
        tables = page.locator("table")
        table_count = tables.count()
        target = None
        headers = None

        for i in range(table_count):
            candidate = tables.nth(i)
            hs = candidate.locator("thead th").all_inner_texts()
            normalized = [norm(h) for h in hs]
            if "bibnumber" in normalized and "name" in normalized:
                target = candidate
                headers = [clean(h) for h in hs]
                break

        if target is None:
            title = page.title()
            body = clean(page.locator("body").inner_text())[:6000]
            print(f"Discovery diagnostics: title={title!r}, tables={table_count}")
            print(body)
            browser.close()
            raise RuntimeError("Could not locate the Köridő individual-results table.")

        # DataTables normally keeps only one page in the DOM. Ask the live
        # DataTable instance to render all rows first; the fallback below can
        # still walk through pages if that is not supported.
        try:
            target.evaluate(
                """
                table => {
                    if (window.jQuery && jQuery.fn && jQuery.fn.dataTable &&
                        jQuery.fn.dataTable.isDataTable(table)) {
                        jQuery(table).DataTable().page.len(-1).draw(false);
                    }
                }
                """
            )
            page.wait_for_timeout(3000)
        except Exception:
            pass

        bib_index = next(i for i, h in enumerate(headers) if norm(h) == "bibnumber")
        name_index = next(i for i, h in enumerate(headers) if norm(h) == "name")
        country_index = next((i for i, h in enumerate(headers) if norm(h) == "country"), None)
        category_index = next((i for i, h in enumerate(headers) if norm(h) == "category"), None)

        def collect_rows():
            return target.locator("tbody tr").evaluate_all(
                """
                trs => trs.map(tr => Array.from(tr.querySelectorAll('td'))
                    .map(td => (td.innerText || '').trim()))
                """
            )

        all_rows = []
        seen_page_keys = set()

        for _ in range(40):
            current = collect_rows()
            page_key = "\n".join("|".join(r) for r in current)
            if page_key in seen_page_keys:
                break
            seen_page_keys.add(page_key)
            all_rows.extend(current)

            next_buttons = target.locator(
                ".dataTables_paginate .next, .paginate_button.next, "
                "button[aria-label*='Next'], a[aria-label*='Next']"
            )
            if next_buttons.count() == 0:
                break

            nxt = next_buttons.first
            cls = (nxt.get_attribute("class") or "").lower()
            disabled_attr = nxt.get_attribute("disabled") is not None
            if disabled_attr or "disabled" in cls:
                break

            try:
                nxt.click(timeout=3000)
                page.wait_for_timeout(700)
            except Exception:
                break

        browser.close()

    by_bib = {}

    for cells in all_rows:
        if bib_index >= len(cells) or name_index >= len(cells):
            continue

        bib = clean(cells[bib_index])
        name = clean(cells[name_index])
        if not bib or not name or norm(name) in {"name", "country"}:
            continue

        # Keep the Bibnumber column as the identity. The first numeric columns
        # are ranking positions, not bib numbers.
        country = clean(cells[country_index]) if country_index is not None and country_index < len(cells) else ""
        category = clean(cells[category_index]) if category_index is not None and category_index < len(cells) else ""

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
