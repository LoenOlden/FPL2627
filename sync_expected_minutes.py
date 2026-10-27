# Updates data/player_db2.py's "expected_minutes" field from a weekly
# review-source minutes projection, exported as CSV from Google Sheets.
#
# Expected CSV shape (one row per player, some repeated header rows mixed
# in from how the sheet is organized by team block - those are skipped
# automatically): columns are Player, Price, GW3, GW4, GW5, GW6, Total,
# Elite Own%, Last Minutes. The "Player" cell is a multi-line cell like
# "RayaARS \u2022 GKP\n\n94" (name + team abbreviation run together with no
# separator, then position, then an unrelated number on its own line -
# only the name/team/position from the FIRST line are used). The LAST
# column ("Last Minutes") is what actually gets written to
# expected_minutes - nothing else about any player is touched by this
# script (not cost, not team, not position, not xG90/xA90/crdY/etc.).
#
# A price of exactly 99.9m marks a "possible transfer, not confirmed yet"
# placeholder row in the review source - always skipped.
#
# Matching a review row to a db player: web_name + team, which resolved
# 651/652 players cleanly the first time this ran (2026-09-04). Price is
# used as a tiebreaker only if name+team matches more than one db player.
# If a row can't be resolved at all (not found, or still ambiguous after
# the price tiebreak), the script stops WITHOUT writing anything and
# prints exactly what needs manual review or a MANUAL_NAME_OVERRIDES
# entry - it deliberately never guesses.
#
# Usage:  python sync_expected_minutes.py "C:\path\to\reviewminutes.csv"
#         (or just  python sync_expected_minutes.py  if the file is at
#         the DEFAULT_CSV_PATH below)

import csv
import re
import sys

DB_PATH = "data/player_db2.py"
DEFAULT_CSV_PATH = "data/reviewminutes.csv"

ABBR_TO_TEAM = {
    'ARS': 1, 'AVL': 2, 'BOU': 3, 'BRE': 4, 'BHA': 5,
    'CHE': 6, 'COV': 7, 'CRY': 8, 'EVE': 9, 'FUL': 10,
    'HUL': 11, 'IPS': 12, 'LEE': 13, 'LIV': 14, 'MCI': 15,
    'MUN': 16, 'NEW': 17, 'NFO': 18, 'TOT': 19, 'SUN': 20,
}
KNOWN_ABBRS = list(ABBR_TO_TEAM.keys())
NAME_RE = re.compile(r"^(.*?)\s*\u2022\s*(\w+)")
PRICE_RE = re.compile(r"[\u00a3\ufffd]?([\d.]+)m")

# Confirmed name-variants between the review source and our own web_name,
# keyed by (review_name, team_id) -> our web_name. Add to this only after
# confirming via team+price that it's genuinely the same single player,
# not a guess - e.g. "N.Angulo" (review) vs "Angulo" (ours) at Sunderland,
# confirmed 2026-09-04: same team, same £5.0m price, and the OTHER
# Angulo at that club (J.Angulo, a different real player, different
# price) already matched on name alone with no ambiguity.
MANUAL_NAME_OVERRIDES = {
    ("N.Angulo", 20): "Angulo",
}


def parse_review_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))[1:]
    parsed = []
    for r in rows:
        if not r or not r[0].strip():
            continue
        first_line = r[0].strip().split("\n")[0]
        if first_line.strip() == "Player":
            continue  # repeated header row from the sheet's team-block layout
        m = NAME_RE.match(first_line)
        if not m:
            raise SystemExit(f"Could not parse name/team/position from: {first_line!r}")
        name_team = m.group(1).strip()
        team_abbr = next((ab for ab in KNOWN_ABBRS if name_team.endswith(ab)), None)
        if team_abbr is None:
            raise SystemExit(f"Unrecognized team abbreviation in: {name_team!r}")
        name = name_team[: -len(team_abbr)].strip()
        pm = PRICE_RE.search(r[1])
        if not pm:
            raise SystemExit(f"Could not parse price from {r[1]!r} (row for {name})")
        price = float(pm.group(1))
        if abs(price - 99.9) < 0.01:
            continue  # unconfirmed possible-transfer placeholder row
        last_minutes = float(r[8].strip())
        team = ABBR_TO_TEAM[team_abbr]
        name = MANUAL_NAME_OVERRIDES.get((name, team), name)
        parsed.append({"name": name, "team": team, "team_abbr": team_abbr,
                        "price": price, "last_minutes": last_minutes})
    return parsed


def load_db_lines(path):
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    assert raw.startswith("players_data = [\n") and raw.rstrip().endswith("]")
    body = raw[len("players_data = [\n"):raw.rstrip().rfind("]")]
    lines = [l for l in body.split("\n") if l.strip()]
    line_re = re.compile(
        r'"id":\s*(\d+),\s*"web_name":\s*"((?:[^"\\]|\\.)*)",\s*"team":\s*(\d+),'
        r'.*?"cost":\s*([\d.]+),.*?"expected_minutes":\s*([\d.]+)'
    )
    entries = []
    for line in lines:
        m = line_re.search(line)
        if not m:
            raise SystemExit(f"UNPARSEABLE LINE, aborting (nothing written): {line!r}")
        entries.append({
            "id": int(m.group(1)), "web_name": m.group(2), "team": int(m.group(3)),
            "cost": float(m.group(4)), "expected_minutes": float(m.group(5)), "text": line,
        })
    return entries


def sync(csv_path):
    review_rows = parse_review_csv(csv_path)
    entries = load_db_lines(DB_PATH)

    updated, unchanged, not_found, ambiguous = [], [], [], []

    for row in review_rows:
        candidates = [e for e in entries if e["web_name"] == row["name"] and e["team"] == row["team"]]
        if len(candidates) == 0:
            not_found.append(row)
            continue
        if len(candidates) > 1:
            price_matches = [e for e in candidates if abs(e["cost"] - row["price"]) < 0.05]
            if len(price_matches) == 1:
                candidates = price_matches
            else:
                ambiguous.append((candidates, row))
                continue

        e = candidates[0]
        if e["expected_minutes"] == row["last_minutes"]:
            unchanged.append(e)
            continue
        new_text = re.sub(r'"expected_minutes":\s*[\d.]+\}', f'"expected_minutes": {row["last_minutes"]}}}',
                           e["text"], count=1)
        e["text"] = new_text
        e["expected_minutes"] = row["last_minutes"]
        updated.append((e["id"], e["web_name"]))

    print(f"Updated: {len(updated)}  |  already correct: {len(unchanged)}  |  "
          f"not found: {len(not_found)}  |  ambiguous: {len(ambiguous)}")

    if not_found:
        print("\n--- NOT FOUND (no matching db player for name+team) ---")
        for row in not_found:
            print(f"  {row['name']} team={row['team_abbr']} price={row['price']}")
    if ambiguous:
        print("\n--- AMBIGUOUS (name+team matched more than one db player, price didn't disambiguate) ---")
        for candidates, row in ambiguous:
            print(f"  {row['name']} team={row['team_abbr']} price={row['price']}: "
                  f"{[(c['id'], c['cost']) for c in candidates]}")
    if not_found or ambiguous:
        print("\nABORTED - nothing written. Resolve the rows above (fix the name in the sheet, or "
              "add a MANUAL_NAME_OVERRIDES entry once confirmed) and re-run.")
        return

    out = "players_data = [\n" + "\n".join(e["text"] for e in entries) + "\n]\n"
    with open(DB_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print(f"\nWrote {DB_PATH}.")


if __name__ == "__main__":
    sync(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV_PATH)
