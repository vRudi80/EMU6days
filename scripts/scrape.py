import asyncio
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE = "https://korido.hu"
LAP_URL = BASE + "/events/resultTableLaps.php?bib={bib}&rc=3600"
ATHLETES_FILE = Path("data/athletes.json")
RACE_FILE = Path("data/race.json")

# Köridő may return HTTP 500 to plain HTTP clients from hosted runner IPs.
# Try normal requests first, then use a real Chromium browser for failed pages.
WORKERS = int(os.getenv("WORKERS", "8"))
BROWSER_WORKERS = int(os.getenv("BROWSER_WORKERS", "6"))
RETRIES = 1
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

RACE_TIMEZONE = ZoneInfo("Europe/Budapest")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": BASE + "/2026EMU6_result?team=1",
})


def text(el):
    return " ".join(el.stripped_strings) if el else ""


def load_discovered_athletes():
    if not ATHLETES_FILE.exists():
        raise FileNotFoundError("data/athletes.json is missing. Run scripts/discover.py first.")
    with ATHLETES_FILE.open("r", encoding="utf-8") as f:
        athletes = json.load(f)
    if len(athletes) < 50:
        raise RuntimeError(f"Only {len(athletes)} discovered athletes; refusing to scrape an incomplete list")
    return athletes


def load_previous_data():
    if not RACE_FILE.exists():
        return {"athletes": []}
    try:
        with RACE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Previous race data could not be loaded: {e}")
        return {"athletes": []}


def parse_html(bib, html):
    bib = str(bib)
    soup = BeautifulSoup(html, "html.parser")

    name = ""
    bib_found = None
    for row in soup.find_all("tr"):
        cells = [text(c) for c in row.find_all(["td", "th"])]
        if len(cells) >= 2:
            key = cells[0].rstrip(":").strip().lower()
            if key == "name":
                name = cells[1]
            elif key in ("bib", "bibnumber", "bib number"):
                bib_found = cells[1].strip()

    if not name:
        page_text = soup.get_text(" ", strip=True)
        m = re.search(r"Name:\s*(.*?)\s+Bib:\s*([^\s]+)\s+Laps:\s*(\d+)", page_text)
        if m:
            name = m.group(1).strip()
            bib_found = m.group(2).strip()

    table = soup.find("table")
    if not table:
        return None

    rows = []
    for tr in table.find_all("tr"):
        cells = [text(c) for c in tr.find_all(["td", "th"])]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        try:
            lap = int(cells[0])
            km = float(cells[1].replace(",", "."))
            lap_time = cells[2]
            read_time = cells[5]
            dt = datetime.strptime(read_time, "%Y.%m.%d %H:%M:%S").replace(tzinfo=RACE_TIMEZONE)
        except (ValueError, IndexError):
            continue
        rows.append({"lap": lap, "km": km, "lapTime": lap_time, "readTime": dt.isoformat()})

    if not rows:
        return None
    return {"bib": str(bib_found or bib), "name": name or f"Bib {bib}", "laps": rows}


def fetch_page(bib):
    url = LAP_URL.format(bib=str(bib))
    for attempt in range(RETRIES + 1):
        try:
            response = session.get(url, timeout=(5, 8))
            if response.status_code not in RETRYABLE_STATUS:
                response.raise_for_status()
                return response.text
            print(f"bib {bib}: HTTP {response.status_code}, attempt {attempt + 1}/{RETRIES + 1}")
        except requests.RequestException as e:
            print(f"bib {bib}: request failed, attempt {attempt + 1}/{RETRIES + 1}: {e}")
            if attempt == RETRIES:
                raise

        if attempt < RETRIES:
            time.sleep(1.0 + random.uniform(0.0, 0.5))

    raise RuntimeError(f"Could not fetch bib {bib}")


def parse_laps(bib):
    html = fetch_page(bib)
    return parse_html(bib, html)


async def browser_fetch_one(page, bib):
    url = LAP_URL.format(bib=str(bib))
    for attempt in range(2):
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            status = response.status if response else 0
            if status == 200:
                html = await page.content()
                parsed = parse_html(bib, html)
                if parsed:
                    return parsed
            print(f"browser bib {bib}: HTTP {status}, attempt {attempt + 1}/2")
        except Exception as e:
            print(f"browser bib {bib}: {e}, attempt {attempt + 1}/2")
        if attempt == 0:
            await asyncio.sleep(1)
    return None


async def browser_fetch_failed(bibs):
    if not bibs:
        return {}

    print(f"Browser fallback for {len(bibs)} athletes (workers={BROWSER_WORKERS})")
    results = {}
    semaphore = asyncio.Semaphore(BROWSER_WORKERS)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        async def worker(bib):
            async with semaphore:
                page = await browser.new_page(
                    viewport={"width": 1440, "height": 1000},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
                    ),
                    locale="hu-HU",
                )
                try:
                    return bib, await browser_fetch_one(page, bib)
                finally:
                    await page.close()

        values = await asyncio.gather(*(worker(bib) for bib in bibs))
        await browser.close()

    for bib, parsed in values:
        if parsed:
            results[str(parsed["bib"])] = parsed
    return results


def merge_athlete(meta, parsed, previous):
    result = dict(meta)
    result["bib"] = str(meta["bib"])
    if previous:
        for key in ("name", "country", "category"):
            if previous.get(key) and not result.get(key):
                result[key] = previous[key]

    if parsed:
        result["name"] = result.get("name") or parsed["name"]
        old_points = previous.get("points", []) if previous else []
        points_by_lap = {int(p["lap"]): p for p in old_points if p.get("lap") is not None}
        for x in parsed["laps"]:
            points_by_lap[x["lap"]] = {"lap": x["lap"], "t": x["readTime"], "km": x["km"]}
        points = [points_by_lap[k] for k in sorted(points_by_lap)]
        result["points"] = points
        last = parsed["laps"][-1]
        result["laps"] = len(points)
        result["km"] = last["km"]
        result["lastLap"] = last["lapTime"]
        result["lastReadTime"] = last["readTime"]
    else:
        result["points"] = previous.get("points", []) if previous else []
        result["laps"] = previous.get("laps", len(result["points"])) if previous else len(result["points"])
        result["km"] = previous.get("km", 0) if previous else 0
        result["lastLap"] = previous.get("lastLap", "") if previous else ""
        result["lastReadTime"] = previous.get("lastReadTime", "") if previous else ""

    return result


def main():
    discovered = load_discovered_athletes()
    previous_data = load_previous_data()
    previous_by_bib = {str(a["bib"]): a for a in previous_data.get("athletes", [])}

    print(f"Updating {len(discovered)} known athletes (workers={WORKERS}, retries={RETRIES})")

    parsed_by_bib = {}
    failed_bibs = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(parse_laps, a["bib"]): str(a["bib"]) for a in discovered}
        for future in as_completed(futures):
            bib = futures[future]
            try:
                parsed = future.result()
                if parsed:
                    parsed_by_bib[str(parsed["bib"])] = parsed
                else:
                    failed_bibs.append(bib)
            except Exception as e:
                print(f"bib {bib} failed: {e}")
                failed_bibs.append(bib)

    success_ratio = len(parsed_by_bib) / len(discovered)
    print(f"HTTP fetched {len(parsed_by_bib)}/{len(discovered)} athletes ({success_ratio:.0%})")

    # Köridő currently returns HTTP 500 to plain requests from the GitHub
    # runner, while Chromium can access the same individual result pages.
    if failed_bibs:
        browser_results = asyncio.run(browser_fetch_failed(failed_bibs))
        parsed_by_bib.update(browser_results)

    success_ratio = len(parsed_by_bib) / len(discovered)
    print(f"Successfully fetched {len(parsed_by_bib)}/{len(discovered)} athletes ({success_ratio:.0%})")
    if success_ratio < 0.90:
        raise RuntimeError(
            f"Only {len(parsed_by_bib)}/{len(discovered)} athlete pages were fetched; "
            "refusing to publish potentially stale race data"
        )

    out = []
    for meta in discovered:
        bib = str(meta["bib"])
        out.append(merge_athlete(meta, parsed_by_bib.get(bib), previous_by_bib.get(bib)))

    out.sort(key=lambda x: x.get("km", 0), reverse=True)

    data = {
        "event": "XV. EMU 6-Day Race / GOMU 6-Day World Championship",
        "lapKm": 0.8982,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "athletes": out,
    }

    RACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with RACE_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    active = sum(1 for a in out if a.get("laps", 0) > 0)
    print(f"Wrote {len(out)} athletes, {active} with lap data")


if __name__ == "__main__":
    main()
