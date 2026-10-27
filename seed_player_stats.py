# Pre-season one-shot: seeds data/player_db.py with last season's stats so you
# only hand-edit players it couldn't match (new signings, promoted teams).
#
# Sources:
#   LAST_SEASON_CSV  - last season's players_data.csv (FPL API dump)
#                       -> xG90, xA90, crdY (yellow cards per 90)
#   FBREF_CSV        - fbref defensive per-90 stats
#                       -> CBIT90 (= Tackles + Interceptions + Clearances + Blocks per 90)
#
# CBITR90 (needs ball recoveries) is NOT seeded - stays for hand entry.
#
# Matching is by name (FPL ids change between seasons; players change teams).
# Everything unmatched is listed at the end - that's your manual to-do list.
#
# Run AFTER build_player_db.py has created the new season's player_db.py:
#   python seed_player_stats.py

import csv
import importlib.util
import json
import sys
import unicodedata

from config import PLAYER_DB

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LAST_SEASON_CSV = "data/archive_players_data_2526_final.csv"
FBREF_CSV = "data/archive_fbref_defensive_2526.csv"
MIN_MINUTES = 400   # below this, last season's per-90s are noise - skip seeding


def norm(s):
    """lowercase, strip accents, keep letters only - for name matching"""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s.lower() if c.isalpha())


def load_db():
    spec = importlib.util.spec_from_file_location("player_db_module", PLAYER_DB)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["player_db_module"] = mod
    spec.loader.exec_module(mod)
    return mod.players_data


def load_last_season():
    """-> {normalized web_name: stats}, names with collisions dropped (ambiguous)"""
    by_name, collisions = {}, set()
    with open(LAST_SEASON_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                minutes = float(row.get("minutes") or 0)
            except ValueError:
                continue
            if minutes < MIN_MINUTES:
                continue

            def num(field):
                try:
                    return float(row.get(field) or 0)
                except ValueError:
                    return 0.0

            stats = {
                "xG90": num("expected_goals_per_90"),
                "xA90": num("expected_assists_per_90"),
                "crdY": round(num("yellow_cards") / minutes * 90, 3),
            }
            key = norm(row["web_name"])
            if key in by_name:
                collisions.add(key)
            by_name[key] = stats
    for key in collisions:
        del by_name[key]
    return by_name, collisions


def load_fbref():
    """-> {normalized full name: CBIT90}. Also index by surname for fallback."""
    exact, by_surname, surname_collisions = {}, {}, set()
    with open(FBREF_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                cbit = (float(row["Tackles_per90"]) + float(row["Interceptions_per90"])
                        + float(row["Clearances_per90"]) + float(row["Blocks_per90"]))
            except (ValueError, KeyError):
                continue
            exact[norm(row["Player"])] = cbit
            surname = norm(row["Player"].split()[-1])
            if surname in by_surname:
                surname_collisions.add(surname)
            by_surname[surname] = cbit
    for s in surname_collisions:
        del by_surname[s]
    return exact, by_surname


def fbref_lookup(web_name, exact, by_surname):
    """FPL web_name ('M.Salah', 'Saka') vs fbref full name ('Mohamed Salah')."""
    key = norm(web_name)
    if key in exact:
        return exact[key]
    # try last token of web_name as surname ('M.Salah' -> 'salah')
    tokens = web_name.replace(".", " ").split()
    if not tokens:
        return None
    surname = norm(tokens[-1])
    return by_surname.get(surname)


if __name__ == "__main__":
    players = load_db()
    last_season, collisions = load_last_season()
    fb_exact, fb_surname = load_fbref()

    seeded_api, seeded_cbit, unmatched = 0, 0, []
    for p in players:
        key = norm(p["web_name"])
        hit = False

        if key in last_season:
            stats = last_season[key]
            p["xG90"] = stats["xG90"]
            p["xA90"] = stats["xA90"]
            p["crdY"] = stats["crdY"]
            seeded_api += 1
            hit = True

        cbit = fbref_lookup(p["web_name"], fb_exact, fb_surname)
        if cbit is not None and p["position"] != 1:
            p["CBIT90"] = round(cbit, 2)
            seeded_cbit += 1
            hit = True

        if not hit:
            unmatched.append(p)

    with open(PLAYER_DB, "w", encoding="utf-8") as f:
        f.write("players_data = [\n")
        for p in players:
            f.write(f"    {json.dumps(p, ensure_ascii=False)},\n")
        f.write("]\n")

    print(f"Seeded xG90/xA90/crdY for {seeded_api} players from last season's FPL data")
    print(f"Seeded CBIT90 for {seeded_cbit} players from fbref")
    if collisions:
        print(f"Skipped {len(collisions)} ambiguous duplicate names (hand-check): {sorted(collisions)}")
    print(f"\n=== MANUAL TO-DO: {len(unmatched)} unmatched players ===")
    for p in sorted(unmatched, key=lambda x: (x["team"], -x["cost"])):
        print(f"  team {p['team']:2d}  {p['web_name']:25s} pos {p['position']}  {p['cost']:.1f}")
    print("\nCBITR90 is never auto-seeded (needs recoveries data) - hand-edit as before.")
