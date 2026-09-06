import os, re, json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup

BASE = "https://korido.hu"
RESULT = BASE + "/2026EMU6_result?rc=3600&tbl=1"
LAP_URL = BASE + "/events/resultTableLaps.php?bib={bib}&rc=3600"
MAX_ATHLETES = int(os.getenv("MAX_ATHLETES", "0"))  # 0 = all
MAX_BIB = int(os.getenv("MAX_BIB", "500"))
WORKERS = int(os.getenv("WORKERS", "12"))

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 EMU-6-Day-Race-Analyzer/1.0"})

def text(el):
    return " ".join(el.stripped_strings) if el else ""

def parse_main(html):
    soup = BeautifulSoup(html, "html.parser")
    athletes = []
    seen = set()
    for a in soup.find_all("a", href=True):
        m = re.search(r"resultTableLaps\.php\?bib=(\d+)", a["href"])
        if not m:
            continue
        bib = int(m.group(1))
        if bib in seen:
            continue
        seen.add(bib)
        row = a.find_parent("tr")
        cells = row.find_all("td") if row else []
        vals = [text(c) for c in cells]
        athletes.append({
            "bib": bib,
            "name": text(a),
            "country": vals[6] if len(vals) > 6 else "",
            "category": vals[7] if len(vals) > 7 else ""
        })
    return athletes

def parse_laps(bib):
    r = session.get(LAP_URL.format(bib=bib), timeout=20)
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    # The individual page has a stable header: Name / Bib / Laps.
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
        # Fallback for the current Köridő HTML where Name/Bib are plain text.
        page_text = soup.get_text(" ", strip=True)
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
            read_time = cells[5]
            dt = datetime.strptime(read_time, "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            continue
        rows.append({
            "lap": lap,
            "km": km,
            "lapTime": cells[2],
            "readTime": dt.isoformat()
        })

    if not rows:
        return None
    return {"bib": bib_found or bib, "name": name or f"Bib {bib}", "laps": rows}

def main():
    # First try the official result page. Köridő currently renders its result rows
    # dynamically, so a normal HTTP request can contain no athlete links at all.
    athletes = []
    try:
        r = session.get(RESULT, timeout=30)
        r.raise_for_status()
        athletes = parse_main(r.text)
    except Exception as e:
        print(f"Main result page unavailable: {e}")

    by_bib = {a["bib"]: a for a in athletes}

    # Reliable fallback: the individual lap pages are server-rendered and expose
    # all lap data. Probe the possible bib range when the main table is empty.
    bibs = list(by_bib.keys()) if by_bib else list(range(1, MAX_BIB + 1))
    if MAX_ATHLETES and len(bibs) > MAX_ATHLETES:
        bibs = bibs[:MAX_ATHLETES]

    out = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(parse_laps, bib): bib for bib in bibs}
        for f in as_completed(futures):
            bib = futures[f]
            try:
                parsed = f.result()
                if not parsed:
                    continue
                a = by_bib.get(parsed["bib"], {"bib": parsed["bib"], "name": parsed["name"], "country": "", "category": ""})
                laps = parsed["laps"]
                last = laps[-1]
                a.update({
                    "name": a.get("name") or parsed["name"],
                    "laps": len(laps),
                    "km": last["km"],
                    "lastLap": last["lapTime"],
                    "lastReadTime": last["readTime"],
                    "points": [{"t": x["readTime"], "km": x["km"]} for x in laps]
                })
                out.append(a)
            except Exception as e:
                print(f"bib {bib} failed: {e}")

    # Remove duplicates and sort by current distance.
    unique = {a["bib"]: a for a in out}
    out = sorted(unique.values(), key=lambda x: x["km"], reverse=True)

    data = {
        "event": "XV. EMU 6-Day Race / GOMU 6-Day World Championship",
        "lapKm": 0.8982,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "athletes": out
    }
    os.makedirs("data", exist_ok=True)
    with open("data/race.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {len(out)} athletes")

if __name__ == "__main__":
    main()
