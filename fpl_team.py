# Fetches a manager's live squad from the public FPL API so the solver
# can be pre-filled instead of hand-typing 15 names/ids.
#
# Free transfers: the FPL API doesn't expose "free transfers remaining" as a
# field, so fetch_free_transfers() replays the manager's season history
# (per-event transfers, hit costs, chips) instead. Known gap: one-off
# league-wide FT top-ups (e.g. the mid-season AFCON boost) can't be seen
# from public data, so the result can be off after one - the value can be
# overridden by hand for that reason.

from datetime import datetime, timezone

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
PICKS_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/event/{gw}/picks/"
TRANSFERS_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/transfers/"
HISTORY_URL = "https://fantasy.premierleague.com/api/entry/{team_id}/history/"


def _latest_locked_event(bootstrap):
    """Latest event whose deadline has passed - i.e. the last one whose
    picks are actually visible via the public /picks/ endpoint (it 404s
    for any event before its own deadline). Deliberately NOT gated on
    bootstrap's "finished" flag: that only flips after every match in the
    gameweek is played AND bonus points are confirmed, which can lag the
    deadline by several days - using it here left the squad sync stuck
    showing the previous gameweek's team well after a new deadline (and
    a real transfer) had already passed."""
    now = datetime.now(timezone.utc)
    locked = [e for e in bootstrap["events"]
              if datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")) <= now]
    if not locked:
        return None
    return max(locked, key=lambda e: e["id"])


def current_start_week():
    """-> int, the next gameweek whose deadline HASN'T passed yet - the
    real, deadline-derived "current gameweek", no team ID needed. Reuses
    _latest_locked_event (the same live FPL bootstrap-static deadline
    data fetch_team() already uses for a real synced squad) so there's
    only ever ONE source of truth for "what gameweek is it" - not a
    second, separately-computed approximation from fixtures.csv's own
    Kickoff timestamps (which carry no timezone marker, a real ambiguity
    risk right around a deadline moment)."""
    bootstrap = requests.get(BOOTSTRAP_URL, headers=HEADERS, timeout=15).json()
    last_event = _latest_locked_event(bootstrap)
    if last_event is None:
        next_events = [e for e in bootstrap["events"] if not e["finished"]]
        return min((e["id"] for e in next_events), default=1)
    return last_event["id"] + 1


def fetch_free_transfers(team_id, last_event_id):
    """Free transfers available for the gameweek AFTER last_event_id, by
    replaying the manager's history from the public /history/ endpoint.
    Rules replayed: 1 FT after the first gameweek, +1 per gameweek, capped
    at 5; transfers beyond the available FTs are paid hits (cost // 4) and
    don't use FTs; a Wildcard/Free Hit week uses none, so the bank just
    grows by 1. Falls back to 1 if history can't be fetched."""
    try:
        hist = requests.get(HISTORY_URL.format(team_id=team_id), headers=HEADERS, timeout=15).json()
        events = {e["event"]: e for e in hist["current"]}
        chips = {c["event"]: c["name"] for c in hist["chips"]}
    except Exception:
        return 1
    if not events:
        return 1
    ft = 1  # FTs available for the gameweek after the manager's first one
    for ev in range(min(events) + 1, last_event_id + 1):
        e = events.get(ev)
        if e is None:  # gameweek with no entry: nothing used, bank +1
            ft = min(5, ft + 1)
            continue
        if chips.get(ev) in ("wildcard", "freehit"):
            ft = min(5, ft + 1)
            continue
        hits = e["event_transfers_cost"] // 4
        free_used = max(0, e["event_transfers"] - hits)
        ft = min(5, max(0, ft - free_used) + 1)
    return ft


def fetch_team(team_id):
    """-> {"squad_ids": [...15 ids...], "bank": float, "squad_value": float,
    "total_value": float, "start_week": int,
    "free_transfers": int (replayed from history), "picks_gw": int or None}
    Raises ValueError on a bad/unknown team id or before GW1's deadline.

    entry_history.value (FPL's own "Team Value") is based on each owned
    player's CURRENT market price, NOT their real sell price - confirmed
    2026-09-04 by summing current prices for a real squad and matching
    entry_history.value exactly, while summing real sell prices (below)
    fell short by exactly the squad's total unrealized gain. Using that
    figure as a transfer budget lets a solver spend unrealized gains as
    if they were cash, which the real FPL app then rejects as insufficient
    funds. So squad_value/total_value here are recomputed from real sell
    prices (fetch_sell_prices) instead of trusted from FPL directly -
    every caller gets the correct budget
    automatically, with no separate downstream correction needed."""
    bootstrap = requests.get(BOOTSTRAP_URL, headers=HEADERS, timeout=15).json()
    last_event = _latest_locked_event(bootstrap)

    if last_event is None:
        # Preseason: no finished gameweek yet, nothing to fetch.
        next_events = [e for e in bootstrap["events"] if not e["finished"]]
        start_week = min((e["id"] for e in next_events), default=1)
        return {"squad_ids": [], "bank": None, "squad_value": None, "total_value": None,
                "start_week": start_week, "free_transfers": 1, "picks_gw": None}

    picks_gw = last_event["id"]
    resp = requests.get(PICKS_URL.format(team_id=team_id, gw=picks_gw), headers=HEADERS, timeout=15)
    if resp.status_code == 404:
        raise ValueError(f"No team found for id {team_id} (or it has no picks yet).")
    resp.raise_for_status()
    data = resp.json()

    squad_ids = [p["element"] for p in data["picks"]]
    bank = data["entry_history"]["bank"] / 10
    start_week = picks_gw + 1

    sell_prices = fetch_sell_prices(team_id, squad_ids)
    squad_value = round(sum(sell_prices.get(pid, 0.0) for pid in squad_ids), 1)
    total_value = round(bank + squad_value, 1)

    return {"squad_ids": squad_ids, "bank": bank, "squad_value": squad_value, "total_value": total_value,
            "start_week": start_week, "free_transfers": fetch_free_transfers(team_id, picks_gw),
            "picks_gw": picks_gw}


def fetch_sell_prices(team_id, squad_ids):
    """Real per-player sell price for each of the given (currently-owned)
    player ids - fully public, no login needed, despite FPL's own
    Transfers page pulling the equivalent PP/SP numbers from an
    authenticated endpoint (/api/my-team/, needs a Bearer token from the
    browser's own logged-in session - not something this server has).
    We reconstruct the same numbers instead:
      - purchase price = the price paid in this player's most recent
        "transferred in" event, from the PUBLIC /transfers/ endpoint - or,
        if they were never transferred in (an original GW1 pick, still
        held), bootstrap-static's now_cost minus cost_change_start (their
        price at the start of the season - also public).
      - FPL's real rule, applied on top: sell price = current price if it
        hasn't risen since purchase, else purchase price + half of any
        rise, rounded down to the nearest GBP 0.1m. Done here in integer
        tenths-of-a-pound-million (the API's native unit, e.g. 55 =
        GBP 5.5m) so the "round down" is exact integer floor division,
        never float rounding. Verified against hand-worked examples:
        5.5->5.6 sells at 5.5, ->5.7 sells at 5.6, ->5.9 and ->6.0 both
        sell at 5.7 (profit 4 and 5 both floor-halve to 2).
    -> {player_id: sell_price_float}. Only covers the given squad_ids -
    the rest of the player pool is always bought/valued at current market
    price, which needs no correction (no purchase history to speak of)."""
    bootstrap = requests.get(BOOTSTRAP_URL, headers=HEADERS, timeout=15).json()
    now_cost = {e["id"]: e["now_cost"] for e in bootstrap["elements"]}
    start_cost = {e["id"]: e["now_cost"] - e["cost_change_start"] for e in bootstrap["elements"]}

    transfers = requests.get(TRANSFERS_URL.format(team_id=team_id), headers=HEADERS, timeout=15).json()
    # A player could in principle be bought, sold, and re-bought within a
    # season - keep only the LATEST transfer-in per player id, since
    # that's what determines today's purchase price.
    purchase_cost = {}
    latest_key = {}
    for t in transfers:
        pid = t["element_in"]
        key = (t["event"], t["time"])
        if pid not in latest_key or key > latest_key[pid]:
            latest_key[pid] = key
            purchase_cost[pid] = t["element_in_cost"]

    result = {}
    for pid in squad_ids:
        cur = now_cost.get(pid)
        if cur is None:
            continue
        pur = purchase_cost.get(pid, start_cost.get(pid, cur))
        sell = pur + (cur - pur) // 2 if cur > pur else cur
        result[pid] = sell / 10
    return result


def fetch_current_prices(player_ids):
    """Live current market price (bootstrap-static now_cost) for the given
    player ids -> {player_id: price_float}. Used to spot when the local
    hand-edited database (data/player_db.py -> output/final_player_data.py,
    refreshed by fetch_fpl.py + priceupdate.py) has drifted from FPL's
    real live price - that refresh is a separate manual pipeline, nothing
    here writes to it automatically, so staleness is expected until you
    rerun it."""
    bootstrap = requests.get(BOOTSTRAP_URL, headers=HEADERS, timeout=15).json()
    now_cost = {e["id"]: e["now_cost"] for e in bootstrap["elements"]}
    return {pid: now_cost[pid] / 10 for pid in player_ids if pid in now_cost}
