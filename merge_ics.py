#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Slår ihop flera ICS-flöden till en (combined.ics).
- Läser iCal-URL:er från env ICS_URLS (en per rad).
- Duplicat tas bort via UID.
- Sorterar på DTSTART.
- Behåller originalhändelserna oförändrade (inkl. tidszoner, alarm etc).

Valfria env:
  MERGE_NAME  = Kalendernamn i headern (default: "Sammanslagen kalender")
  OUT_ICS     = Filnamn (default: combined.ics)
"""

import os, sys, re, datetime as dt
import requests

def unfold_ics(text: str) -> list[str]:
    # RFC5545 line folding: rader som börjar med space är fortsättning av föregående rad
    lines = text.splitlines()
    out = []
    for line in lines:
        if line.startswith(" ") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out

def parse_events(ics_text: str):
    lines = unfold_ics(ics_text)
    events = []
    in_evt = False
    cur = []
    for ln in lines:
        if ln.startswith("BEGIN:VEVENT"):
            in_evt = True
            cur = [ln]
        elif ln.startswith("END:VEVENT"):
            if in_evt:
                cur.append(ln)
                events.append("\n".join(cur))
                in_evt = False
                cur = []
        elif in_evt:
            cur.append(ln)
    return events

def extract_uid(evt: str) -> str | None:
    m = re.search(r"\nUID:(.+)", evt)
    return m.group(1).strip() if m else None

def extract_dtstart(evt: str) -> str:
    # används för sortering, fallback om saknas
    m = re.search(r"\nDTSTART[^\n:]*:([0-9TZ]+)", evt)
    return m.group(1).strip() if m else "99999999T000000Z"

def fetch(url: str) -> str:
    r = requests.get(url, timeout=45, headers={"User-Agent":"ICS-Merger/1.0"})
    r.raise_for_status()
    return r.text

def build_calendar(name: str, events_sorted: list[str]) -> str:
    now = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    head = [
        "BEGIN:VCALENDAR",
        "PRODID:-//ics-merger//github//",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{name}",
        "METHOD:PUBLISH",
    ]
    tail = ["END:VCALENDAR"]
    return "\n".join(head + events_sorted + tail) + "\n"

def main():
    urls_blob = os.environ.get("ICS_URLS", "").strip()
    if not urls_blob:
        print("ERROR: ICS_URLS env saknas (en iCal-URL per rad).", file=sys.stderr)
        sys.exit(2)
    out_name = os.environ.get("MERGE_NAME", "Sammanslagen kalender")
    out_file = os.environ.get("OUT_ICS", "combined.ics")

    urls = [u.strip() for u in urls_blob.splitlines() if u.strip()]
    seen = set()
    all_events = []

    for u in urls:
        try:
            txt = fetch(u)
        except Exception as e:
            print(f"VARNING: kunde inte hämta {u}: {e}", file=sys.stderr)
            continue
        evts = parse_events(txt)
        for e in evts:
            uid = extract_uid(e) or f"NOUID-{hash(e)}"
            if uid in seen:
                continue
            seen.add(uid)
            all_events.append(e)

    # sortera på DTSTART
    all_events.sort(key=lambda e: extract_dtstart(e))

    cal = build_calendar(out_name, all_events)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(cal)
    print(f"Klar: {out_file} med {len(all_events)} händelser från {len(urls)} kalendrar.")

if __name__ == "__main__":
    main()
