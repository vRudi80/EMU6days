import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://korido.hu"
LAP_URL = BASE + "/events/resultTableLaps.php?bib={bib}&rc=3600"
ATHLETES_FILE = Path("data/athletes.json")
RACE_FILE = Path("data/race.json")
WORKERS = int(os.getenv("WORKERS", "16"))

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 EMU-6-Day-Race-Analyzer/1.0"})


def text(el):
    return " ".join(el.stripped_strings) if el else ""


def load_discovered_athletes():
    if not ATHLETES_FILE.exists():
        raise FileNotFoundError(
            "data/athletes.json is missing. Run scripts/discover.py first."
        )
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


def parse_laps(bib):
    r = session.get(LAP_URL.format(bib=bib), timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    name = ""
    bib_found = None
    for row in soup.find_all("tr"):
        cells = [text(c) for c in row.find_all(["td", "th"])]
        if len(cells) >= 2:
            key = cells[0].rstrip(":").strip().lower()
            if key == "name":
                name = cells[1]
            elif key in ("bib", "bibnumber", "bib number"):
                try:
                    bib_found = int(cells[1])
                except ValueError:
                    pass

    if not name:
        page_text = soup.get_text(" ", strip=True)
        import re
        m = re.search(r"Name:\s*(.*?)\s+Bib:\s*(\d+)\s+Laps:\s*(\d+)", page_text)
        if m:
            name = m.group(1).strip()
            bib_found = int(m.group(2))

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
            dt = datetime.strptime(read_time, "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            continue
        rows.append({
            "lap": lap,
            "km": km,
            "lapTime": lap_time,
            "readTime": dt.isoformat(),
        })

    if not rows:
        return None
    return {"bib": bib_found or bib, "name": name or f"Bib {bib}", "laps": rows}


def merge_athlete(meta, parsed, previous):
    """Merge newly downloaded laps into the already published history."""
    old_points = previous.get("points", []) if previous else []
    old_by_lap = {}
    for point in old_points:
        # Older data only has t/km, so lap is optional.
        if "lap" in point:
            old_by_lap[int(point["lap"])] = point

    new_by_lap = {}
    if parsed:
        for lap in parsed["laps"]:
            new_by_lap[int(lap["lap"])] = {
                "lap": int(lap["lap"]),
                "t": lap["readTime"],
                "km": lap["km"],
            }

    # If old points came from the previous format, keep them. New data replaces
    # the same lap when available and adds only genuinely new laps.
    merged = list(old_by_lap.values())
    merged_by_key = {p.get("lap"): p for p in merged if p.get("lap") is not None}
    for lap, point in new_by_lap.items():
        merged_by_key[lap] = point

    # Preserve legacy points without lap numbers, then append new/updated laps.
    legacy = [p for p in old_points if p.get("lap") is None]
    points = legacy + list(merged_by_key.values())
    points.sort(key=lambda p: (p.get("t", ""), p.get("lap", 0)))

    result = dict(meta)
    if previous:
        for key in ("name", "country", "category"):
            if previous.get(key) and not result.get(key):
                result[key] = previous[key]

    if parsed:
        result["name"] = result.get("name") or parsed["name"]
        result["points"] = points
        last = parsed["laps"][-1]
        result["laps"] = len(points)
        result["km"] = last["km"]
        result["lastLap"] = last["lapTime"]
        result["lastReadTime"] = last["readTime"]
    else:
        # Keep an athlete visible even if their page is temporarily unavailable.
        result["points"] = points
        result["laps"] = previous.get("laps", len(points)) if previous else len(points)
        result["km"] = previous.get("km", 0) if previous else 0
        result["lastLap"] = previous.get("lastLap", "") if previous else ""
        result["lastReadTime"] = previous.get("lastReadTime", "") if previous else ""

    return result


def main():
    discovered = load_discovered_athletes()
    previous_data = load_previous_data()
    previous_by_bib = {int(a["bib"]): a for a in previous_data.get("athletes", [])}

    print(f"Updating {len(discovered)} known athletes (no bib-range probing)")

    parsed_by_bib = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {
            ex.submit(parse_laps, int(a["bib"])): int(a["bib"])
            for a in discovered
        }
        for future in as_completed(futures):
            bib = futures[future]
            try:
                parsed = future.result()
                if parsed:
                    parsed_by_bib[int(parsed["bib"])] = parsed
            except Exception as e:
                print(f"bib {bib} failed: {e}")

    out = []
    for meta in discovered:
        bib = int(meta["bib"])
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
