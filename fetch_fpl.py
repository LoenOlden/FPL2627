# Fetches FPL bootstrap data -> data/players_data.csv
# and fixtures -> data/fixtures.csv.
# Run this whenever prices/fixtures change (usually once per gameweek).
#
# fixtures.csv has a Probability column (default 1.00). You hand-edit it for
# blank/double gameweek rescheduling odds (Ben Crellin style) - re-running this
# script preserves your manual Probability edits for unchanged fixtures.

import csv
import os
import requests
from datetime import datetime

from config import FIXTURES_CSV, PLAYERS_CSV

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

PLAYER_FIELDS = [
    'id', 'first_name', 'second_name', 'web_name', 'team', 'position', 'cost', 'total_points',
    'expected_goals', 'expected_assists', 'expected_goal_involvements', 'expected_goals_conceded',
    'minutes', 'goals_scored', 'assists', 'clean_sheets', 'goals_conceded', 'own_goals',
    'penalties_saved', 'penalties_missed', 'yellow_cards', 'red_cards', 'saves', 'bonus',
    'bps', 'starts', 'expected_goals_per_90', 'saves_per_90', 'expected_assists_per_90',
    'expected_goal_involvements_per_90', 'expected_goals_conceded_per_90', 'goals_conceded_per_90',
    'starts_per_90', 'clean_sheets_per_90',
    'clearances_blocks_interceptions', 'tackles', 'recoveries', 'defensive_contribution_per_90',
]


def fetch_json(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def save_players(bootstrap):
    with open(PLAYERS_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=PLAYER_FIELDS)
        writer.writeheader()
        for p in bootstrap['elements']:
            row = {field: p.get(field, '') for field in PLAYER_FIELDS}
            row['position'] = p['element_type']
            row['cost'] = p['now_cost'] / 10
            writer.writerow(row)
    print(f"Saved {len(bootstrap['elements'])} players to {PLAYERS_CSV}")


def load_existing_probabilities():
    """Keep hand-edited Probability values across re-fetches."""
    probs = {}
    if os.path.exists(FIXTURES_CSV):
        with open(FIXTURES_CSV, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                key = (row['Gameweek'], row['Home Team'], row['Away Team'])
                probs[key] = row['Probability']
    return probs

"""
def save_fixtures(fixtures, bootstrap):
    team_id_to_name = {t['id']: t['name'] for t in bootstrap['teams']}
    existing_probs = load_existing_probabilities()

    with open(FIXTURES_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Gameweek", "Home Team", "Away Team", "Kickoff", "Probability"])
        count = 0
        for fx in fixtures:
            if fx['kickoff_time'] is None or fx['event'] is None:
                continue
            gw = f"GW{fx['event']}"
            home = team_id_to_name[fx['team_h']]
            away = team_id_to_name[fx['team_a']]
            kickoff = datetime.fromisoformat(fx['kickoff_time'].replace("Z", "")).strftime('%Y-%m-%d %H:%M:%S')
            prob = existing_probs.get((gw, home, away), "1.00")
            writer.writerow([gw, home, away, kickoff, prob])
            count += 1
    print(f"Saved {count} fixtures to {FIXTURES_CSV} (manual probabilities preserved)")
"""


if __name__ == "__main__":
    bootstrap = fetch_json("https://fantasy.premierleague.com/api/bootstrap-static/")
    #fixtures = fetch_json("https://fantasy.premierleague.com/api/fixtures/")
    save_players(bootstrap)
    #save_fixtures(fixtures, bootstrap)
