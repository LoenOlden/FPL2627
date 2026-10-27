# One-command weekly update for data/player_db2.py. Fetches the latest
# FPL data, then runs three phases against player_db2.py, in order:
#
#   1. PRICES: any player already in the db whose cost differs from the
#      fresh FPL price gets it updated in place (no reordering from this
#      alone - a price drifting within its team+position block over time
#      without a re-sort is expected, pre-existing behavior, not a bug).
#
#   2. NEW PLAYERS: any id in the fresh data not yet in the db is inserted
#      at the correct spot - matched by team, then position, then price
#      tier, following the same team-block / position-block / descending-
#      price-tier ordering the rest of the file already uses. A brand-new
#      price tier (e.g. a big-money signing priced above anyone else at
#      that position for that team) is placed above the existing tiers,
#      exactly like a lower/never-seen-before tier goes below them.
#
#   3. TRANSFERS: any existing player whose fresh-data team differs from
#      their db team (moved to a different Premier League club) is
#      relocated to the correct spot in their NEW team's block, and their
#      team-level stats (saves90, TeamXG90, TeamXGC90, TeamAttCoef,
#      TeamDefCoef - identical for every player on a given team) are
#      updated to match the new team, copied from an existing teammate
#      there.
#
# None of the three phases ever touch web_name, position, xG90, xA90,
# crdY, CBIT90, CBITR90, or expected_minutes - those are hand-edited /
# synced separately (expected_minutes: sync_expected_minutes.py, from a
# weekly review-source export, a genuinely different trigger/cadence so
# it's deliberately its own script, not folded in here).
#
# Idempotent - safe to re-run even if nothing changed, it'll just report
# zero updates in every phase.
#
# Deliberately does NOT touch data/player_db.py at all (decided
# 2026-09-04: player_db.py is now purely a manual copy-paste from
# player_db2.py once you're happy with a week's changes, not
# auto-synced by anything - old priceupdate.py, which used to
# auto-update player_db.py's price too, was retired for this reason).
#
# Usage:  python sync_player_db2.py

import csv
import json
import re

import fetch_fpl

DB_PATH = "data/player_db2.py"
CSV_PATH = "data/players_data.csv"

LINE_RE = re.compile(
    r'\{"id":\s*(\d+),\s*"web_name":\s*"((?:[^"\\]|\\.)*)",\s*"team":\s*(\d+),\s*"position":\s*(\d+),\s*"cost":\s*([\d.]+),'
)
TEAM_STATS_RE = re.compile(
    r'"saves90":\s*([\-\d.]+),\s*"TeamXG90":\s*([\-\d.]+),\s*"TeamXGC90":\s*([\-\d.]+),'
    r'\s*"TeamAttCoef":\s*([\-\d.]+),\s*"TeamDefCoef":\s*([\-\d.]+)'
)


def load_db_lines(path):
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    assert raw.startswith("players_data = [\n") and raw.rstrip().endswith("]")
    body = raw[len("players_data = [\n"):raw.rstrip().rfind("]")]
    lines = [l for l in body.split("\n") if l.strip()]

    entries = []
    for line in lines:
        m = LINE_RE.search(line)
        if not m:
            raise SystemExit(f"UNPARSEABLE LINE, aborting (nothing written): {line!r}")
        entries.append({
            "id": int(m.group(1)), "web_name": m.group(2),
            "team": int(m.group(3)), "position": int(m.group(4)), "cost": float(m.group(5)),
            "text": line,
        })
    return entries


def load_csv_rows(path):
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {int(r["id"]): r for r in reader}


def team_stats_text(entry_text):
    m = TEAM_STATS_RE.search(entry_text)
    if not m:
        raise SystemExit(f"Could not find team-stats fields in: {entry_text!r}")
    return m.group(0)


def find_insert_index(entries, team, position, cost):
    """Same ordering rule used throughout the file: team blocks ascending,
    position sub-blocks ascending within a team, price tiers DESCENDING
    within a team+position - a new/never-seen price tier goes above lower
    tiers and below higher ones, exactly like a brand-new signing would."""
    exact_idx = [i for i, e in enumerate(entries)
                 if e["team"] == team and e["position"] == position and e["cost"] == cost]
    if exact_idx:
        return exact_idx[-1] + 1

    same_block_idx = [i for i, e in enumerate(entries) if e["team"] == team and e["position"] == position]
    if same_block_idx:
        lower_idx = [i for i in same_block_idx if entries[i]["cost"] < cost]
        if lower_idx:
            return lower_idx[0]
        return same_block_idx[-1] + 1

    team_idx = [i for i, e in enumerate(entries) if e["team"] == team]
    if team_idx:
        lower_pos_idx = [i for i in team_idx if entries[i]["position"] < position]
        if lower_pos_idx:
            return lower_pos_idx[-1] + 1
        return team_idx[0]

    raise SystemExit(f"No existing entries at all for team {team} - cannot place a new row there "
                      f"(need at least one existing teammate to copy team-level stats from)")


def make_new_line(pid, web_name, team, position, cost, donor_stats_text):
    crdY = 0.054 if position == 1 else 0.169
    m = TEAM_STATS_RE.search(donor_stats_text)
    saves90, txg, txgc, tatt, tdef = m.groups()
    return (
        f'    {{"id": {pid}, "web_name": {json.dumps(web_name, ensure_ascii=False)}, "team": {team}, '
        f'"position": {position}, "cost": {cost}, "xG90": 0.0, "xA90": 0.0, "crdY": {crdY}, '
        f'"CBIT90": 0.0, "CBITR90": 0.0, "saves90": {saves90}, "TeamXG90": {txg}, '
        f'"TeamXGC90": {txgc}, "TeamAttCoef": {tatt}, "TeamDefCoef": {tdef}, '
        f'"expected_minutes": 0.0}},'
    )


def sync():
    print("Fetching latest FPL data...")
    bootstrap = fetch_fpl.fetch_json("https://fantasy.premierleague.com/api/bootstrap-static/")
    fetch_fpl.save_players(bootstrap)

    entries = load_db_lines(DB_PATH)
    csv_rows = load_csv_rows(CSV_PATH)

    # --- Phase 1: prices ---
    repriced = []
    for e in entries:
        row = csv_rows.get(e["id"])
        if row is None:
            continue
        new_cost = float(row["cost"])
        if new_cost != e["cost"]:
            new_text = re.sub(r'"cost":\s*[\d.]+', f'"cost": {new_cost}', e["text"], count=1)
            e["text"], old_cost, e["cost"] = new_text, e["cost"], new_cost
            repriced.append(f"id={e['id']:4d} {e['web_name']:20s} {old_cost:.1f} -> {new_cost:.1f}")

    db_ids = {e["id"] for e in entries}

    # --- Phase 2: new players ---
    added = []
    new_ids = sorted(pid for pid in csv_rows if pid not in db_ids)
    for pid in new_ids:
        row = csv_rows[pid]
        web_name, team, position, cost = row["web_name"], int(row["team"]), int(row["position"]), float(row["cost"])
        donor = next((e for e in entries if e["team"] == team), None)
        if donor is None:
            print(f"  SKIPPED id={pid} {web_name}: no existing player for team {team} to copy team-stats from")
            continue
        insert_at = find_insert_index(entries, team, position, cost)
        new_line = make_new_line(pid, web_name, team, position, cost, donor["text"])
        entries.insert(insert_at, {"id": pid, "web_name": web_name, "team": team, "position": position,
                                    "cost": cost, "text": new_line})
        added.append(f"id={pid:4d} {web_name:20s} -> team {team}, pos {position}, cost {cost}")

    # --- Phase 3: transfers (team mismatch on existing players) ---
    moved = []
    i = 0
    while i < len(entries):
        e = entries[i]
        row = csv_rows.get(e["id"])
        if row is None:
            i += 1
            continue
        new_team = int(row["team"])
        if new_team == e["team"]:
            i += 1
            continue

        old_team = e["team"]
        entries.pop(i)  # don't advance i - next element shifts into position i

        donor = next((x for x in entries if x["team"] == new_team), None)
        if donor is None:
            entries.insert(i, e)  # put it back unchanged, can't relocate without a donor
            print(f"  SKIPPED transfer id={e['id']} {e['web_name']}: no existing player for new team "
                  f"{new_team} to copy team-stats from")
            i += 1
            continue

        new_team_stats = team_stats_text(donor["text"])
        new_text = re.sub(r'"team":\s*\d+', f'"team": {new_team}', e["text"], count=1)
        new_text = TEAM_STATS_RE.sub(new_team_stats, new_text, count=1)

        insert_at = find_insert_index(entries, new_team, e["position"], e["cost"])
        entries.insert(insert_at, {"id": e["id"], "web_name": e["web_name"], "team": new_team,
                                    "position": e["position"], "cost": e["cost"], "text": new_text})
        moved.append(f"id={e['id']:4d} {e['web_name']:20s} team {old_team} -> {new_team}")
        # don't advance i - re-check whatever is now at index i

    print(f"\nPrices updated: {len(repriced)}  |  New players: {len(added)}  |  Transfers: {len(moved)}")

    if repriced:
        print(f"\n--- {len(repriced)} price change(s) ---")
        for line in repriced:
            print(" ", line)
    if added:
        print(f"\n--- {len(added)} new player(s) ---")
        for line in added:
            print(" ", line)
    if moved:
        print(f"\n--- {len(moved)} transfer(s) ---")
        for line in moved:
            print(" ", line)

    if not repriced and not added and not moved:
        print("\nNo changes - player_db2.py was already fully in sync.")
        return

    out = "players_data = [\n" + "\n".join(e["text"] for e in entries) + "\n]\n"
    with open(DB_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print(f"\nWrote {DB_PATH} ({len(entries)} total players).")


if __name__ == "__main__":
    sync()
