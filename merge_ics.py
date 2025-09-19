#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Slår ihop flera ICS-flöden till en (combined.ics) och prefixar SUMMARY
med etiketter per källkalender. Fixar även å/ä/ö-mojibake från vissa flöden.

Env:
  ICS_URLS   = iCal-URL:er, en per rad (ordningen används för labeling)
  CAL_LABELS = Etiketter, en per rad (matchar ordningen i ICS_URLS)
  MERGE_NAME = Kalendernamn (default: "Sammanslagen kalender")
  OUT_ICS    = Utfil (default: combined.ics)
"""

import os, sys, re, datetime as dt
import requests

def unfold_ics(text: str) -> list[str]:
    # RFC5545 folding: rader som börjar med space fortsätter föregående rad
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
    events, in_evt, cur = [], False, []
    for ln in lines:
        if ln.startswith("BEGIN:VEVENT"):
            in_evt, cur = True, [ln]
        elif ln.startswith("END:VEVENT"):
            if in_evt:
                cur.append(ln)
                events.append("\n".join(cur))
            in_evt, cur = False, []
        elif in_evt:
            cur.append(ln)
    return events

def extract_uid(evt: str) -> str | None:
    m = re.search(r"\nUID:(.+)", evt)
    return m.group(1).strip() if m else None

def extract_dtstart(evt: str) -> str:
    m = re.search(r"\nDTSTART[^\n:]*:([0-9TZW+-]+)", evt)
    return m.group(1).strip() if m else "99999999T000000Z"

def fetch(url: str) -> str:
    r = requests.get(url, timeout=45, headers={"User-Agent":"ICS-Merger/1.2"})
    r.raise_for_status()
    raw = r.content  # bytes, inte r.text (vi bestämmer kodning själva)
    # Försök i denna ordning för att undvika mojibake (SportAdmin m.fl.)
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")

def get_calendar_name(ics_text: str) -> str | None:
    m = re.search(r"\nX-WR-CALNAME:(.+)", ics_text)
    if m:
        return m.group(1).strip()
    m = re.search(r"\nPRODID:(.+)", ics_text)
    return m.group(1).strip() if m else None

def _demojibake(s: str) -> str:
    # Rätta typisk UTF8->latin1-mojibake: "GrÃ¶t" -> "Gröt"
    if "Ã" in s or "Â" in s:
        try:
            return s.encode("latin-1").decode("utf-8")
        except Exception:
            return s
    return s

def add_prefix_to_summary(evt: str, label: str | None) -> str:
    # Avmoba mojibake i SUMMARY och lägg ev. label-prefix
    def repl(m):
        head, val = m.group(1), m.group(2)
        val = _demojibake(val)
        if label:
            if val.startswith(f"[{label}] ") or re.match(r"^\[[^\]]+\]\s", val):
                return f"{head}{val}"
            val = f"[{label}] {val}"
        return f"{head}{val}"
    return re.sub(r"(?m)^(SUMMARY[^\n:]*:)(.*)$", repl, evt, count=1)

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

    labels_blob = os.environ.get("CAL_LABELS", "").strip()
    labels = [l.strip() for l in labels_blob.splitlines() if l.strip()] if labels_blob else []

    out_name = os.environ.get("MERGE_NAME", "Sammanslagen kalender")
    out_file = os.environ.get("OUT_ICS", "combined.ics")

    urls = [u.strip() for u in urls_blob.splitlines() if u.strip()]
    seen = set()
    all_events = []

    for idx, u in enumerate(urls):
        try:
            txt = fetch(u)
        except Exception as e:
            print(f"VARNING: kunde inte hämta {u}: {e}", file=sys.stderr)
            continue

        # Label för denna källa
        label = labels[idx] if idx < len(labels) else (get_calendar_name(txt) or None)

        evts = parse_events(txt)
        for e in evts:
            uid = extract_uid(e) or f"NOUID-{hash(e)}"
            if uid in seen:
                continue
            seen.add(uid)

            e2 = add_prefix_to_summary(e, label)
            all_events.append(e2)

    all_events.sort(key=lambda e: extract_dtstart(e))

    cal = build_calendar(out_name, all_events)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(cal)
    print(f"Klar: {out_file} med {len(all_events)} händelser från {len(urls)} kalendrar. Labels: {', '.join(labels) or '(inga)'}")

if __name__ == "__main__":
    main()
