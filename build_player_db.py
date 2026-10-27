# Builds / refreshes data/player_db.py - the hand-editable player database.
#
# Replaces old createupdated.py + sync_updated_players.py:
#   - First run (no player_db.py): creates it from players_data.csv, seeding
#     xG90/xA90/saves from the FPL API per-90 fields where available.
#   - Later runs: adds new players, updates costs/teams, refreshes the
#     team-level fields from team_ratings.py, and PRESERVES your hand-edited
#     per-player values (xG90, xA90, crdY, CBIT90, CBITR90, expected_minutes).
#
# The db stays a .py file with named keys on purpose - it is the hand-editing
# surface for pre-season stat entry from fbref/understat/whoscored.

import csv
import importlib.util
import json
import os
import sys

from config import (DEFAULT_CRDY_GK, DEFAULT_CRDY_OUTFIELD, PLAYER_DB,
                    PLAYERS_CSV, team_mappings)
import team_ratings as tr

HAND_EDITED_KEYS = ["xG90", "xA90", "crdY", "CBIT90", "CBITR90", "expected_minutes", "xmins_by_gw"]

# Below this many minutes last season, a per-90 CBIT/CBITR rate is too noisy
# to seed from - leave it at 0.0 for hand entry instead. Matches the
# reliability floor seed_player_stats.py uses for xG90/xA90/crdY.
MIN_MINUTES_FOR_CBIT = 400


def load_csv_players():
    players = {}
    with open(PLAYERS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pid = int(row["id"])

            def num(field):
                try:
                    return float(row.get(field) or 0)
                except ValueError:
                    return 0.0

            minutes = num("minutes")
            cbit90 = cbitr90 = 0.0
            if minutes >= MIN_MINUTES_FOR_CBIT:
                cbi = num("clearances_blocks_interceptions")
                tackles = num("tackles")
                recoveries = num("recoveries")
                cbit90 = round((cbi + tackles) / minutes * 90, 2)
                cbitr90 = round((cbi + tackles + recoveries) / minutes * 90, 2)

            players[pid] = {
                "id": pid,
                "web_name": row["web_name"],
                "team": int(row["team"]),
                "position": int(row["position"]),
                "cost": float(row["cost"]),
                "xG90_api": num("expected_goals_per_90"),
                "xA90_api": num("expected_assists_per_90"),
                "CBIT90_api": cbit90,
                "CBITR90_api": cbitr90,
            }
    return players


def load_existing_db():
    if not os.path.exists(PLAYER_DB):
        return None
    spec = importlib.util.spec_from_file_location("player_db_module", PLAYER_DB)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["player_db_module"] = mod
    spec.loader.exec_module(mod)
    return {p["id"]: p for p in mod.players_data}


def team_fields(team_id):
    abbr = team_mappings.get(team_id, "")
    return {
        "saves90": tr.saves90.get(abbr, 3.0),
        "TeamXG90": tr.team_xg90.get(abbr, 1.4),
        "TeamXGC90": tr.team_xgc90.get(abbr, 1.5),
        "TeamAttCoef": tr.team_coef_Att.get(abbr, 1.0),
        "TeamDefCoef": tr.team_coef_Def.get(abbr, 1.0),
    }


def make_player(csv_p, existing=None):
    pos = csv_p["position"]
    default_crdy = DEFAULT_CRDY_GK if pos == 1 else DEFAULT_CRDY_OUTFIELD

    player = {
        "id": csv_p["id"],
        "web_name": csv_p["web_name"],
        "team": csv_p["team"],
        "position": pos,
        "cost": csv_p["cost"],
        "xG90": csv_p["xG90_api"],
        "xA90": csv_p["xA90_api"],
        "crdY": default_crdy,
        "CBIT90": csv_p["CBIT90_api"],
        "CBITR90": csv_p["CBITR90_api"],
    }
    player.update(team_fields(csv_p["team"]))
    player["expected_minutes"] = 0.0

    if existing:
        for key in HAND_EDITED_KEYS:
            if key not in existing:
                continue
            # CBIT90/CBITR90 default to 0.0 until seeded/hand-filled - treat
            # an existing 0.0 as "not filled yet", not as a deliberate edit,
            # so a fresh API-seeded value can actually land.
            if key in ("CBIT90", "CBITR90") and existing[key] == 0.0:
                continue
            player[key] = existing[key]

    return player


def write_db(players):
    players.sort(key=lambda p: (p["team"], p["position"], -p["cost"]))
    with open(PLAYER_DB, "w", encoding="utf-8") as f:
        f.write("players_data = [\n")
        for p in players:
            f.write(f"    {json.dumps(p, ensure_ascii=False)},\n")
        f.write("]\n")


if __name__ == "__main__":
    csv_players = load_csv_players()
    existing = load_existing_db() or {}

    new_ids, kept = [], 0
    result = []
    for pid, csv_p in sorted(csv_players.items()):
        old = existing.get(pid)
        result.append(make_player(csv_p, old))
        if old:
            kept += 1
        else:
            new_ids.append(pid)

    write_db(result)
    print(f"Wrote {len(result)} players to {PLAYER_DB}")
    print(f"  preserved hand-edits for {kept} existing players")
    if new_ids:
        print(f"  added {len(new_ids)} new players: {new_ids}")
    gone = set(existing) - set(csv_players)
    if gone:
        print(f"  NOTE: {len(gone)} players no longer in FPL data (removed): {sorted(gone)}")
