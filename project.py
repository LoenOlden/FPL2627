# Runs the points model over the fixture list and writes BOTH solver inputs:
#   output/projection.csv        (per-player projections)
#   output/final_player_data.py  (player_gameweek_data, for solver.py)
# One calculation, two writers - the two files can never disagree.
#
# Usage: set START_GW / END_GW below, then  python project.py

import csv
import importlib.util
import json
import sys

import pandas as pd

from config import (FINAL_PLAYER_DATA, FIXTURES_CSV, PLAYER_DB, PROJECTION_CSV,
                    position_mapping, team_mappings, team_names_to_abbr)
from points_model import fixture_points, player_xmins_for_gw

START_GW = 1
END_GW = 38


def load_players():
    spec = importlib.util.spec_from_file_location("player_db_module", PLAYER_DB)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["player_db_module"] = mod
    spec.loader.exec_module(mod)
    return mod.players_data


def calculate_all(players, fixtures, start_gw, end_gw):
    """-> {player_id: {gw: points}} summed over all fixtures in each GW
    (double gameweeks add up naturally; blanks contribute nothing)."""
    points = {p["id"]: {gw: 0.0 for gw in range(start_gw, end_gw + 1)} for p in players}

    team_of = {p["id"]: team_mappings.get(p["team"], "?") for p in players}

    for gw in range(start_gw, end_gw + 1):
        for _, fx in fixtures[fixtures["Gameweek"] == gw].iterrows():
            home = team_names_to_abbr.get(fx["Home Team"])
            away = team_names_to_abbr.get(fx["Away Team"])
            prob = float(fx["Probability"])
            if home is None or away is None or prob <= 0:
                continue

            for p in players:
                abbr = team_of[p["id"]]
                if abbr == home:
                    pts = fixture_points(p, away, True, prob, gw)
                elif abbr == away:
                    pts = fixture_points(p, home, False, prob, gw)
                else:
                    continue
                points[p["id"]][gw] += round(pts, 2)

    return points


def write_projection_csv(players, points, start_gw, end_gw):
    fieldnames = ['Pos', 'ID', 'Name', 'BV', 'SV', 'Team']
    for gw in range(start_gw, end_gw + 1):
        fieldnames += [f'{gw}_xMins', f'{gw}_Pts']

    with open(PROJECTION_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in sorted(players, key=lambda x: x["id"]):
            row = {
                'Pos': position_mapping.get(p["position"], '?'),
                'ID': p["id"],
                'Name': p["web_name"],
                'BV': p["cost"],
                'SV': p["cost"],
                'Team': team_mappings.get(p["team"], '?'),
            }
            for gw in range(start_gw, end_gw + 1):
                row[f'{gw}_xMins'] = int(player_xmins_for_gw(p, gw))
                row[f'{gw}_Pts'] = round(points[p["id"]][gw], 2)
            writer.writerow(row)
    print(f"Wrote {PROJECTION_CSV}")


def write_final_player_data(players, points, start_gw, end_gw):
    with open(FINAL_PLAYER_DATA, 'w', encoding='utf-8') as f:
        f.write("player_gameweek_data = [\n")
        for p in sorted(players, key=lambda x: x["id"]):
            entry = {
                "id": p["id"],
                "name": p["web_name"],
                "position": p["position"],
                "team": team_mappings.get(p["team"], "?"),
                "price": p["cost"],
            }
            for gw in range(start_gw, end_gw + 1):
                entry[f"GW{gw}"] = round(points[p["id"]][gw], 2)
            f.write(f"    {json.dumps(entry, ensure_ascii=False)},\n")
        f.write("]\n")
    print(f"Wrote {FINAL_PLAYER_DATA}")


if __name__ == "__main__":
    players = load_players()
    fixtures = pd.read_csv(FIXTURES_CSV)
    fixtures["Gameweek"] = fixtures["Gameweek"].str.replace("GW", "").astype(int)

    points = calculate_all(players, fixtures, START_GW, END_GW)
    write_projection_csv(players, points, START_GW, END_GW)
    write_final_player_data(players, points, START_GW, END_GW)
