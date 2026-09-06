# EMU 6-Day Race – Live Race Analyzer

A GitHub Pages-compatible visualization for the XV. EMU 6-Day Race / GOMU 6-Day World Championship.

## Features

- cumulative distance vs. elapsed race time
- every lap as a data point
- visible flat sections during long breaks
- Top 10 / 20 / 50 / 100 / all
- Hungarian-only filter
- athlete search
- current ranking table
- GitHub Actions refresh every 15 minutes

## Setup

1. Create a public GitHub repository, for example `emu-6-day-live`.
2. Upload all files from this project.
3. In GitHub: **Settings → Pages → Deploy from a branch → main → /(root)**.
4. In **Actions**, run **Update race data** once manually.
5. The scheduled workflow then refreshes `data/race.json` every 15 minutes.

The scraper reads the public Köridő result table and each athlete's detailed lap page. The event page states that one lap is 898.2 m and the detailed pages expose lap number, cumulative km, lap time and ReadTime.
