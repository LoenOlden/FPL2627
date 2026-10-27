# Season-wide constants and team mappings for 2026/27.
# This is the ONLY place these live - every script imports from here.
# When promotions/relegations happen, update the three maps below together.

SEASON = "2026/27"

# FPL API team id -> abbreviation
team_mappings = {
    1: 'ARS', 2: 'AVL', 3: 'BOU', 4: 'BRE', 5: 'BHA',
    6: 'CHE', 7: 'COV', 8: 'CRY', 9: 'EVE', 10: 'FUL',
    11: 'HUL', 12: 'IPS', 13: 'LEE', 14: 'LIV', 15: 'MCI',
    16: 'MUN', 17: 'NEW', 18: 'NFO', 19: 'TOT', 20: 'SUN',
}

abbr_to_team_id = {v: k for k, v in team_mappings.items()}

# FPL API full team name -> abbreviation (used for fixtures.csv)
team_names_to_abbr = {
    'Arsenal': 'ARS', 'Aston Villa': 'AVL', 'Bournemouth': 'BOU', 'Brentford': 'BRE', 'Brighton': 'BHA',
    'Chelsea': 'CHE', 'Coventry City': 'COV', 'Crystal Palace': 'CRY', 'Everton': 'EVE', 'Fulham': 'FUL',
    'Hull City': 'HUL', 'Ipswich Town': 'IPS', 'Leeds': 'LEE', 'Liverpool': 'LIV', 'Man City': 'MCI',
    "Man Utd": 'MUN', 'Newcastle': 'NEW', 'Nott\'m Forest': 'NFO', 'Spurs': 'TOT', 'Sunderland': 'SUN',
}

position_mapping = {1: 'G', 2: 'D', 3: 'M', 4: 'F'}

home_coefficient = 1.114
away_coefficient = 0.886

# Yellow-card baseline rates per 90 when a player has no history
DEFAULT_CRDY_GK = 0.054
DEFAULT_CRDY_OUTFIELD = 0.169

# File locations
DATA_DIR = "data"
OUTPUT_DIR = "output"
PLAYER_DB = "data/player_db.py"
PLAYERS_CSV = "data/players_data.csv"
FIXTURES_CSV = "data/fixtures.csv"
REVIEW_MINS_JSON = "data/reviewmins.json"
PROJECTION_CSV = "output/projection.csv"
FINAL_PLAYER_DATA = "output/final_player_data.py"
