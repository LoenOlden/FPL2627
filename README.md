# FPL 2026/27

Projects expected points for every Fantasy Premier League player and gameweek, then picks transfers, hits and chips (Wildcard, Free Hit, Bench Boost, Triple Captain) with a solver.

## Install

```
pip install requests pandas scipy pulp highspy
```

## Every week

Run these in order:

1. `python fetch_fpl.py`  
   Downloads current players, prices and fixtures into `data/`.
2. `python build_player_db.py`  
   Updates `data/player_db.py` with new prices and new players.
3. `python update_xmins.py`  
   Adds expected minutes per gameweek (needs `data/reviewmins.json`).
4. `python project.py`  
   Calculates the projections into `output/`.
5. `python solver.py`  
   Prints the transfer and chip plan.

Before step 5, open `solver.py` and set your squad, bank and chips in the settings block at the top. Set `TEAM_ID` to your FPL team id to load your squad automatically.

## First time only

- `python seed_player_stats.py` fills `data/player_db.py` from last season's stats. Set the file paths at the top of the script first.
- Edit `team_ratings.py` with team strength numbers for the new season.

## Files

| File | What it does |
|---|---|
| `fetch_fpl.py` | Downloads players and fixtures |
| `build_player_db.py` | Builds and updates the player database |
| `seed_player_stats.py` | Fills the database with last season's stats |
| `update_xmins.py` | Adds expected minutes |
| `project.py` | Calculates expected points |
| `points_model.py` | The points formulas |
| `team_ratings.py` | Team strength numbers |
| `solver.py` | Transfer and chip planner |
| `fpl_team.py` | Loads your squad from the FPL API |
| `config.py` | Team names and season settings |
