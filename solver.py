# Unified FPL solver: transfers, free-transfer banking, -4 hits, and all four
# chips (Wildcard, Free Hit, Bench Boost, Triple Captain) in ONE model.
#
# Key ideas that make the chips clean:
#   - The persistent squad evolves week to week via transfer balance, ALWAYS.
#   - A Free Hit week uses a SECOND squad variable set (fh_squad); the
#     persistent squad is frozen that week (no transfers), so "reverting"
#     after the FH is automatic - the persistent squad never changed.
#   - Wildcard doesn't relax any squad rule; it just makes transfers free and
#     unlimited that week.
#   - Bench Boost adds bench points to the objective (linearized product).
#   - Triple Captain adds one extra multiple of the captain's points.
#   - Free transfers bank 1..5 per current FPL rules; extra transfers cost 4.
#
# Solver: uses HiGHS if available (pip install highspy) - much faster than CBC
# for chip planning. Falls back to CBC. TIME_LIMIT always applies, so you get
# the best plan found so far instead of missing a deadline.
#
# Usage: edit the CONFIG block, then  python solver.py

import os
import time

import pandas as pd
import pulp

import importlib.util
import sys

from config import FIXTURES_CSV, team_names_to_abbr

# Windows console: print player names with accents safely
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# =====================  CONFIG  =====================
# Set this to your FPL team ID to auto-fill INITIAL_SQUAD/BUDGET/START_WEEK
# below from the live FPL API instead of
# typing them in by hand every week. Leave None to use the manual values
# as-is (e.g. preseason, or exploring a hypothetical squad).
TEAM_ID = None

BUDGET = 100.0          # total squad value you can hold (price basis)
INITIAL_BANK = 0.0      # actual spare cash at START_WEEK (BUDGET minus what the squad is
                        # worth) - only used to print a running bank balance per week in
                        # report(), never fed into the solve itself. Auto-filled from the
                        # real FPL bank figure when TEAM_ID is synced below; for a manual
                        # squad, set this yourself if you want the bank line to be accurate.
INITIAL_FTS = 1         # free transfers at the first planned week - auto-filled from your real history when TEAM_ID is set
START_WEEK = 4          # first gameweek to plan (the upcoming deadline)
NUM_WEEKS = 6           # planning horizon length
DECAY_RATE = 1.0       # per-week discount on future points (1.0 = none)
HIT_COST = 4.0          # cost of a paid transfer - a REAL FPL rule, don't touch this to tune behavior
FT_VALUE = 1.75          # flat points penalty on EVERY transfer made, in any week - NOT a real FPL
                        # rule, purely a bias so the solver doesn't burn a transfer for a marginal
                        # gain that a future surprise (injury, postponement, price rise) could
                        # easily have made unnecessary. A transfer's own full-remaining-horizon
                        # point gain (already summed across every week in the objective) simply
                        # needs to exceed FT_VALUE to be worth making - a flat trigger point, not
                        # scaled by weeks left. 1.5 clears easily for a real upgrade; 3 is very
                        # cautious; a higher value effectively stops transferring at all. 0
                        # disables this entirely (transfer for any positive gain, no matter how
                        # small - today's old behavior before this option existed).
BENCH_WEIGHT = 0.07     # fraction of a bench player's points valued (autosub proxy)
TIME_LIMIT = 250        # seconds; best-found solution is returned at the limit
MIN_XMINS_FILTER = 0.3  # drop players whose max GW score in horizon is below this (speed)

# Your current 15 (leave empty [] to build a squad from scratch, e.g. preseason).
# Ignored (overwritten) if TEAM_ID is set above.
INITIAL_SQUAD = [250, 109, 4, 418, 387, 426, 367, 229, 175, 368, 208, 154, 106, 346, 295]

BANNED_PLAYERS = []     # never selected
LOCKED_PLAYERS = []     # must be in the persistent squad every week

# Chip availability. For each chip: None = not available,
# "any" = solver chooses the week, or an int = forced to that gameweek.
CHIPS = {
    "WC": None,
    "FH": None,
    "BB": None,
    "TC": None,
}
# ====================================================


SELL_PRICES = {}  # {player_id: real sell price}, filled in by sync_team_from_fpl()
                   # for the current squad only - empty (=> fall back to
                   # current market price, today's old behavior) whenever
                   # TEAM_ID is unset or a manual INITIAL_SQUAD is used.


def sync_team_from_fpl():
    """If TEAM_ID is set, overwrite INITIAL_SQUAD/BUDGET/START_WEEK/
    SELL_PRICES from the live FPL API - uses fpl_team.py. BUDGET is set from total_value
    (FPL's own combined bank+squad "Team Value" figure, already correct
    for price rises in aggregate); SELL_PRICES gives the real PER-PLAYER
    breakdown the solver needs to value a sell decision correctly instead
    of assuming every owned player sells at today's market price."""
    global INITIAL_SQUAD, BUDGET, INITIAL_BANK, INITIAL_FTS, START_WEEK, SELL_PRICES
    if TEAM_ID is None:
        return
    import fpl_team
    data = fpl_team.fetch_team(TEAM_ID)
    if not data["squad_ids"]:
        print(f"TEAM_ID {TEAM_ID}: preseason, no picks yet - using the manual "
              f"INITIAL_SQUAD/BUDGET/START_WEEK above instead.")
        return
    INITIAL_SQUAD = data["squad_ids"]
    START_WEEK = data["start_week"]
    SELL_PRICES = fpl_team.fetch_sell_prices(TEAM_ID, INITIAL_SQUAD)
    # BUDGET = real spendable cash, NOT data["total_value"]. Confirmed
    # 2026-09-04 (a real player having actually risen in price finally
    # made this testable): FPL's own total_value/squad_value are based on
    # CURRENT market prices, not real discounted sell prices - summing
    # current prices for this exact squad matched FPL's total_value
    # exactly (99.7), while summing real sell prices gave 99.5, a 0.2m
    # gap tracing exactly to Gakpo (+0.1) and Palmer (+0.1) having risen
    # since purchase. Using total_value as BUDGET let the model treat
    # that unrealized 0.2m as spendable, which isn't real money until
    # sold (and even then only half of it, per FPL's own rule) - caused
    # a live, reproducible case of the solver proposing a transfer the
    # real FPL app then rejected for insufficient funds.
    real_sell_total = sum(SELL_PRICES.get(pid, 0.0) for pid in INITIAL_SQUAD)
    BUDGET = round(data["bank"] + real_sell_total, 1)
    INITIAL_BANK = data["bank"]
    INITIAL_FTS = data["free_transfers"]  # replayed from the real transfer history
    print(f"Synced team {TEAM_ID}: {len(INITIAL_SQUAD)} players, bank £{data['bank']}m, "
          f"real sell value £{real_sell_total:.1f}m, budget £{BUDGET}m, start GW{START_WEEK}, "
          f"free transfers {INITIAL_FTS}")
    print(f"Real sell prices fetched for {len(SELL_PRICES)}/{len(INITIAL_SQUAD)} owned players "
          f"(any not fetched fall back to current market price).")


def report_squad_prices(players):
    """Prints DB price (what the solver actually uses to value a player)
    next to FPL's live current price and, when synced from TEAM_ID, real
    sell price - so a stale local database (data/player_db.py, only
    refreshed when you run fetch_fpl.py + priceupdate.py, NOT touched by
    TEAM_ID syncing) is visible instead of silently wrong. Only checks
    the current 15 - the local db can legitimately be stale for players
    you don't own without it mattering to this plan."""
    if not INITIAL_SQUAD:
        return
    import fpl_team
    squad = players[players["id"].isin(INITIAL_SQUAD) | players["name"].isin(INITIAL_SQUAD)]
    live = fpl_team.fetch_current_prices(squad["id"].tolist())

    print("\nSquad prices (DB = what the solver uses | CP = live FPL price | SP = real sell price):")
    stale = []
    for _, r in squad.sort_values("name").iterrows():
        cp = live.get(r["id"])
        sp = SELL_PRICES.get(r["id"])
        cp_s = f"{cp:.1f}" if cp is not None else "?"
        sp_s = f"{sp:.1f}" if sp is not None else "-"
        flag = ""
        if cp is not None and abs(cp - r["price"]) > 0.001:
            flag = "  <-- DB is STALE, rerun fetch_fpl.py + priceupdate.py"
            stale.append(r["name"])
        print(f"  {r['name']:20s} DB {r['price']:.1f}  CP {cp_s:>4s}  SP {sp_s:>4s}{flag}")
    if stale:
        print(f"\n{len(stale)} squad player(s) have a stale DB price - the solver is valuing them "
              f"using the OLD price, not today's real market price: {', '.join(stale)}")


def load_players():
    spec = importlib.util.spec_from_file_location("fpd", "output/final_player_data.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fpd"] = mod
    spec.loader.exec_module(mod)

    weeks = list(range(START_WEEK, START_WEEK + NUM_WEEKS))
    rows = []
    conflicts = []
    for p in mod.player_gameweek_data:
        is_banned = p["name"] in BANNED_PLAYERS or p["id"] in BANNED_PLAYERS
        if is_banned:
            # A banned player is unconditionally dropped from the pool
            # below, EVEN if they're currently owned or locked in - so
            # banning a player you own is a contradiction (the plan has
            # no way to keep OR sell someone who isn't in the pool at
            # all), not just an unusual preference. Catch it here, with
            # a clear, name-resolved message, rather than letting it
            # surface later as a confusing "Initial squad entries not
            # found" crash quoting a bare player id.
            if p["name"] in INITIAL_SQUAD or p["id"] in INITIAL_SQUAD \
                    or p["name"] in LOCKED_PLAYERS or p["id"] in LOCKED_PLAYERS:
                conflicts.append(p["name"])
            continue
        if p.get("position") == 5:
            continue
        scores = {w: float(p.get(f"GW{w}", 0.0)) for w in weeks}
        keep = (p["name"] in INITIAL_SQUAD or p["id"] in INITIAL_SQUAD
                or p["name"] in LOCKED_PLAYERS or p["id"] in LOCKED_PLAYERS
                or max(scores.values()) >= MIN_XMINS_FILTER)
        if not keep:
            continue
        rows.append({"id": p["id"], "name": p["name"], "position": p["position"],
                     "team": p["team"], "price": float(p["price"]), **{f"GW{w}": s for w, s in scores.items()}})
    if conflicts:
        raise SystemExit(f"{', '.join(conflicts)} {'is' if len(conflicts) == 1 else 'are'} in "
                          f"BANNED_PLAYERS but also currently owned or locked in - a banned player "
                          f"can't be held at all, so there's no way to keep or sell them. Remove "
                          f"them from BANNED_PLAYERS (transfer them out first, in this plan or in "
                          f"real FPL, if you want them gone).")
    df = pd.DataFrame(rows).reset_index(drop=True)
    print(f"Loaded {len(df)} players after filtering")
    return df


def build_and_solve(players):
    weeks = list(range(START_WEEK, START_WEEK + NUM_WEEKS))
    P = list(players.index)
    pts = {(i, w): players.loc[i, f"GW{w}"] * (DECAY_RATE ** (w - START_WEEK)) for i in P for w in weeks}
    price = players["price"].to_dict()
    pos = players["position"].to_dict()
    team = players["team"].to_dict()
    POS_COUNT = {1: 2, 2: 5, 3: 5, 4: 3}

    # sell_price differs from price (current market price) ONLY for
    # players in SELL_PRICES - i.e. the up-to-15 currently-owned squad,
    # when synced from a real TEAM_ID. Everyone else is only ever a
    # candidate to BUY, so market price is already their correct value -
    # this deliberately does NOT touch fh_squad's constraint below: a
    # Free Hit swaps the whole squad for one week and reverts automatically,
    # modeling its economics against real sell prices too is a separate,
    # more involved change (would need to know which FH-squad picks
    # overlap the persistent squad you already own for free) and is out
    # of scope for this fix.
    id_to_idx = {pid: idx for idx, pid in players["id"].items()}
    sell_price = dict(price)
    for pid, sp in SELL_PRICES.items():
        idx = id_to_idx.get(pid)
        if idx is not None:
            sell_price[idx] = sp

    prob = pulp.LpProblem("FPL", pulp.LpMaximize)

    squad = pulp.LpVariable.dicts("squad", (P, weeks), cat="Binary")
    fh_squad = pulp.LpVariable.dicts("fh_squad", (P, weeks), cat="Binary")
    lineup = pulp.LpVariable.dicts("lineup", (P, weeks), cat="Binary")
    bench = pulp.LpVariable.dicts("bench", (P, weeks), cat="Binary")
    captain = pulp.LpVariable.dicts("captain", (P, weeks), cat="Binary")
    tin = pulp.LpVariable.dicts("tin", (P, weeks), cat="Binary")
    tout = pulp.LpVariable.dicts("tout", (P, weeks), cat="Binary")
    y_tc = pulp.LpVariable.dicts("y_tc", (P, weeks), cat="Binary")   # TC'd captain
    y_bb = pulp.LpVariable.dicts("y_bb", (P, weeks), cat="Binary")   # bench player counted fully (BB)

    use = {}
    for chip in ("WC", "FH", "BB", "TC"):
        use[chip] = pulp.LpVariable.dicts(f"use_{chip}", weeks, cat="Binary")
        avail = CHIPS.get(chip)
        if avail is None:
            for w in weeks:
                prob += use[chip][w] == 0
        elif isinstance(avail, int):
            for w in weeks:
                prob += use[chip][w] == (1 if w == avail else 0)
        prob += pulp.lpSum(use[chip][w] for w in weeks) <= 1
    for w in weeks:
        prob += pulp.lpSum(use[c][w] for c in use) <= 1, f"one_chip_week_{w}"

    ft = pulp.LpVariable.dicts("ft", weeks, lowBound=1, upBound=5, cat="Integer")
    hits = pulp.LpVariable.dicts("hits", weeks, lowBound=0, cat="Integer")

    # Initial squad anchor (constants for week START_WEEK - 1)
    if INITIAL_SQUAD:
        # entries may be web_name strings or ids (or a mix) - use ids for any
        # name that's shared by more than one player (e.g. "Palmer").
        init_mask = players["name"].isin(INITIAL_SQUAD) | players["id"].isin(INITIAL_SQUAD)
        init_idx = set(players[init_mask].index)
        matched_keys = set(players.loc[list(init_idx), "name"]) | set(players.loc[list(init_idx), "id"])
        missing = set(INITIAL_SQUAD) - matched_keys
        if missing:
            raise SystemExit(f"Initial squad entries not found in data: {sorted(missing, key=str)}")
        if len(init_idx) != 15:
            raise SystemExit(f"Initial squad has {len(init_idx)} matched players, need 15 "
                             f"(a name in the list probably matches more than one player - use that player's id instead)")
        init = {i: (1 if i in init_idx else 0) for i in P}
    else:
        init = None  # squad built freely in the first week (preseason mode)

    # Real cash available to spend, at the moment the plan starts. When
    # synced from a real TEAM_ID, INITIAL_BANK is already the true figure
    # (see sync_team_from_fpl). For a manual/no-TEAM_ID squad, INITIAL_BANK
    # defaults to 0.0 - which would incorrectly zero out any unspent room
    # between the squad's own current-price total and BUDGET, a real
    # behaviour change from the old squad-value-cap model. Auto-derive it
    # here instead so manual mode keeps working the same way it always
    # did: BUDGET minus what the given squad costs at today's price (no
    # per-player sell-price knowledge exists for a manual squad anyway -
    # every player is only ever valued at current price in that case).
    effective_initial_bank = INITIAL_BANK
    if TEAM_ID is None and init is not None:
        effective_initial_bank = round(BUDGET - sum(price[i] for i in P if init[i]), 1)

    for w in weeks:
        # ---- persistent squad rules ----
        prob += pulp.lpSum(squad[i][w] for i in P) == 15
        for po, cnt in POS_COUNT.items():
            prob += pulp.lpSum(squad[i][w] for i in P if pos[i] == po) == cnt
        for t in players["team"].unique():
            prob += pulp.lpSum(squad[i][w] for i in P if team[i] == t) <= 3
        # Real affordability is enforced below via actual cash-flow
        # tracking (bank[w] >= 0), not a static per-player value cap here
        # - see the "real cash-flow budget tracking" block after this loop
        # for why a static cap gets this wrong for a rebought player.

        # ---- free hit squad rules (all scale with use_FH: zeroed when unused) ----
        prob += pulp.lpSum(fh_squad[i][w] for i in P) == 15 * use["FH"][w]
        for po, cnt in POS_COUNT.items():
            prob += pulp.lpSum(fh_squad[i][w] for i in P if pos[i] == po) == cnt * use["FH"][w]
        for t in players["team"].unique():
            prob += pulp.lpSum(fh_squad[i][w] for i in P if team[i] == t) <= 3
        prob += pulp.lpSum(price[i] * fh_squad[i][w] for i in P) <= BUDGET

        # ---- lineup / bench drawn from the active squad ----
        prob += pulp.lpSum(lineup[i][w] for i in P) == 11
        prob += pulp.lpSum(bench[i][w] for i in P) == 4
        for i in P:
            prob += lineup[i][w] + bench[i][w] <= 1
            prob += lineup[i][w] + bench[i][w] <= squad[i][w] + fh_squad[i][w]
            # On a FH week, only the FH squad may be fielded:
            prob += lineup[i][w] + bench[i][w] <= fh_squad[i][w] + 1 - use["FH"][w]

        # formation
        prob += pulp.lpSum(lineup[i][w] for i in P if pos[i] == 1) == 1
        prob += pulp.lpSum(lineup[i][w] for i in P if pos[i] == 2) >= 3
        prob += pulp.lpSum(lineup[i][w] for i in P if pos[i] == 3) >= 2
        prob += pulp.lpSum(lineup[i][w] for i in P if pos[i] == 4) >= 1

        # captain / triple captain
        prob += pulp.lpSum(captain[i][w] for i in P) == 1
        prob += pulp.lpSum(y_tc[i][w] for i in P) <= use["TC"][w]
        for i in P:
            prob += captain[i][w] <= lineup[i][w]
            prob += y_tc[i][w] <= captain[i][w]

        # bench boost linearization: y_bb = bench AND use_BB
        for i in P:
            prob += y_bb[i][w] <= bench[i][w]
            prob += y_bb[i][w] <= use["BB"][w]
            prob += y_bb[i][w] >= bench[i][w] + use["BB"][w] - 1

        # ---- transfers & squad continuity ----
        prev = {i: (init[i] if init is not None else None) for i in P} if w == START_WEEK else None
        if w == START_WEEK:
            if init is not None:
                for i in P:
                    prob += squad[i][w] == init[i] + tin[i][w] - tout[i][w]
            else:
                # preseason: free squad build, no transfers counted
                for i in P:
                    prob += tin[i][w] == 0
                    prob += tout[i][w] == 0
        else:
            for i in P:
                prob += squad[i][w] == squad[i][w - 1] + tin[i][w] - tout[i][w]

        # no persistent-squad transfers on a Free Hit week
        prob += pulp.lpSum(tin[i][w] for i in P) <= 15 * (1 - use["FH"][w])
        prob += pulp.lpSum(tout[i][w] for i in P) <= 15 * (1 - use["FH"][w])

        # hits: transfers beyond free ones cost 4, unless WC (or FH: 0 transfers anyway)
        tcount = pulp.lpSum(tin[i][w] for i in P)
        prob += hits[w] >= tcount - ft[w] - 15 * use["WC"][w]

        # locked players stay in the persistent squad (entries may be
        # web_name strings or ids)
        for key in LOCKED_PLAYERS:
            idx = players[(players["name"] == key) | (players["id"] == key)].index
            if len(idx):
                prob += squad[idx[0]][w] == 1

    # ---- free transfer banking: ft[w+1] = min(5, ft[w] - paid-for + 1) ----
    prob += ft[START_WEEK] == max(1, min(5, INITIAL_FTS))
    for w in weeks[:-1]:
        tcount_w = pulp.lpSum(tin[i][w] for i in P)
        # hits[w] refunds what wasn't covered by FTs; chips make the bound slack
        prob += ft[w + 1] <= ft[w] - tcount_w + hits[w] + 1 + 15 * (use["WC"][w] + use["FH"][w])
        # ...but a chip week never GRANTS extra FTs: normal +1 accrual only
        prob += ft[w + 1] <= ft[w] + 1

    # ---- real cash-flow budget tracking ----
    # Replaces a static "sum(sell_price[i] * squad[i][w]) <= BUDGET" cap
    # (removed above). That cap valued a player the SAME way in every
    # week they happened to be in the squad, with no memory of whether
    # they were bought that week, held since before START_WEEK, or SOLD
    # and BOUGHT BACK later in the horizon - so a rebought original-squad
    # player kept getting valued at their old discounted sell price
    # forever, understating the real cost of buying them back (you always
    # pay full current market price to buy ANY player, no exceptions -
    # the discount only ever applies once, at the moment of a genuine
    # first sale). Concretely: bought at 7.5, risen to 7.9, sold at the
    # real discount (7.7) - if bought back later, that must cost 7.9
    # (today's price), not 7.7 again. The old constraint would have
    # silently let it cost 7.7, letting the solver "afford" a plan that
    # isn't actually affordable in real FPL. This also directly affects
    # Wildcard weeks (same tin/tout/squad machinery, just hit-free that
    # week) and matters most for exactly the scenario that exposed it: an
    # injured player worth selling for a few blank weeks, then buying
    # back once fit.
    #
    # Fixed via real per-week cash tracking: bank[w] = bank[w-1] +
    # proceeds - cost, bank[w] >= 0 (enforced by the variable's own
    # lowBound). BUY cost is ALWAYS price[i] (current market, no
    # exception - matches FPL's actual rule exactly). SELL proceeds are
    # ALSO always price[i], EXCEPT for the true first-ever sale of a
    # player from the ORIGINAL synced squad, which uses their real
    # discounted sell_price[i] instead - tracked via already_sold/
    # first_sale binaries below so a later resale (of a rebought
    # original, or of any freshly-bought player) correctly falls back to
    # full current price, no discount memory carried forward.
    bank = pulp.LpVariable.dicts("bank", weeks, lowBound=0, cat="Continuous")

    orig_idx = [i for i in P if sell_price[i] != price[i]]  # only original-squad
                                                              # players can ever have
                                                              # a real discount to track
    already_sold = pulp.LpVariable.dicts("already_sold", (orig_idx, weeks), cat="Binary")
    first_sale = pulp.LpVariable.dicts("first_sale", (orig_idx, weeks), cat="Binary")
    for i in orig_idx:
        prob += already_sold[i][weeks[0]] == 0  # nothing sold before the plan starts
        for w in weeks[:-1]:
            # already_sold[w+1] = already_sold[w] OR tout[w] (cumulative)
            prob += already_sold[i][w + 1] >= already_sold[i][w]
            prob += already_sold[i][w + 1] >= tout[i][w]
            prob += already_sold[i][w + 1] <= already_sold[i][w] + tout[i][w]
        for w in weeks:
            # first_sale[w] = tout[w] AND NOT already_sold[w]
            prob += first_sale[i][w] <= tout[i][w]
            prob += first_sale[i][w] <= 1 - already_sold[i][w]
            prob += first_sale[i][w] >= tout[i][w] - already_sold[i][w]

    prev_bank = effective_initial_bank
    for w in weeks:
        if w == START_WEEK and init is None:
            # preseason: the whole squad is built freely as a single lump
            # purchase (tin/tout forced to 0 above so it isn't counted as
            # 15 real transfers against hits/FT) - but it still has to be
            # PAID for, at full current price, out of the starting bank.
            buy_cost_w = pulp.lpSum(price[i] * squad[i][w] for i in P)
            sell_proceeds_w = 0
        else:
            buy_cost_w = pulp.lpSum(price[i] * tin[i][w] for i in P)
            sell_proceeds_w = pulp.lpSum(price[i] * tout[i][w] for i in P) + pulp.lpSum(
                first_sale[i][w] * (sell_price[i] - price[i]) for i in orig_idx
            )
        prob += bank[w] == prev_bank + sell_proceeds_w - buy_cost_w
        prev_bank = bank[w]

    # ---- objective ----
    total = pulp.lpSum(
        pts[i, w] * (lineup[i][w] + captain[i][w] + y_tc[i][w]
                     + BENCH_WEIGHT * bench[i][w] + (1 - BENCH_WEIGHT) * y_bb[i][w])
        for i in P for w in weeks
    )
    # FT_VALUE is a flat penalty on every transfer made (in ANY week,
    # including the very first one) - not a reward for banked ft[w]. An
    # earlier version tried rewarding ft[w] directly, which was a real bug:
    # ft[w+1]'s recurrence constraint below is only an upper bound (<=),
    # and hits[w] sits inside it with a positive coefficient, so the
    # solver could inflate hits[w] beyond what was actually needed (paying
    # the real -4 once) purely to loosen next week's FT ceiling and bank
    # more - profitable whenever the accumulated future bonus outweighed
    # that one-time cost. It also silently never applied to the first
    # week's decision at all, since ft[START_WEEK] is fixed by a
    # constraint, not something the model chooses. Penalizing the tin
    # (transfer-in) decision directly has neither problem: every
    # transfer's own already-summed full-horizon point gain just needs to
    # exceed FT_VALUE to be worth making - a flat trigger point, matching
    # FPLReview's own description, with nothing left to game.
    ft_penalty = FT_VALUE * pulp.lpSum(tin[i][w] for i in P for w in weeks)
    prob += total - HIT_COST * pulp.lpSum(hits[w] for w in weeks) - ft_penalty

    # ---- solve (HiGHS preferred, CBC fallback), always time-limited ----
    solver = None
    try:
        solver = pulp.HiGHS(msg=True, timeLimit=TIME_LIMIT)
        prob.solve(solver)
    except Exception:
        print("HiGHS unavailable (pip install highspy) - falling back to CBC")
        solver = pulp.PULP_CBC_CMD(msg=True, timeLimit=TIME_LIMIT)
        prob.solve(solver)

    status = pulp.LpStatus[prob.status]
    print(f"\nSolver status: {status}   objective: {pulp.value(prob.objective):.2f}")
    if status not in ("Optimal", "Not Solved"):  # Not Solved = stopped at time limit with incumbent
        raise SystemExit("No feasible solution - check budget / initial squad / locks")

    return {"squad": squad, "fh_squad": fh_squad, "lineup": lineup, "bench": bench,
            "captain": captain, "tin": tin, "tout": tout, "use": use,
            "ft": ft, "hits": hits, "weeks": weeks, "sell_price": sell_price,
            "bank": bank, "first_sale": first_sale}


def val(var):
    return var.varValue is not None and var.varValue > 0.5


def load_opponents():
    """-> {(team_abbr, gw): ["OPP(H)", ...]} - list because of double gameweeks."""
    fixtures = pd.read_csv(FIXTURES_CSV)
    fixtures["Gameweek"] = fixtures["Gameweek"].str.replace("GW", "").astype(int)
    opponents = {}
    for _, fx in fixtures.iterrows():
        gw = fx["Gameweek"]
        home = team_names_to_abbr.get(fx["Home Team"])
        away = team_names_to_abbr.get(fx["Away Team"])
        if home is None or away is None:
            continue
        opponents.setdefault((home, gw), []).append(f"{away}(H)")
        opponents.setdefault((away, gw), []).append(f"{home}(A)")
    return opponents


def opp_str(opponents, team, gw):
    fixtures = opponents.get((team, gw))
    return "+".join(fixtures) if fixtures else "-"


def report(players, sol):
    weeks, use, sell_price = sol["weeks"], sol["use"], sol["sell_price"]
    P = list(players.index)
    opponents = load_opponents()

    # ---- recompute the TRUE free-transfer trajectory ----
    # sol["ft"][w].varValue can't be trusted for display: the solver's own
    # ft[w+1] recurrence is only an upper bound (ft[w+1] <= ...), and once
    # FT_VALUE penalizes tin directly instead of rewarding ft[w] (see the
    # objective's comment above), nothing left in the model forces ft[w]
    # up to its true achievable value - it's free to sit anywhere >=1 with
    # no effect on the objective, which showed up as "FT available: 1"
    # staying flat for weeks with zero transfers instead of climbing.
    # This doesn't affect the SOLVE itself (transfer/squad/hit choices are
    # still correctly optimal - hits[w] is independently pinned by its own
    # real -4 cost), only the reported number, so it's fixed by replaying
    # the same real FPL accrual rule in plain Python against the solution's
    # already-confirmed tin/hits values, not by trusting ft[w] itself.
    true_ft = {weeks[0]: max(1, min(5, INITIAL_FTS))}
    for w in weeks[:-1]:
        tcount_w = sum(1 for i in P if val(sol["tin"][i][w]))
        hits_w = round(sol["hits"][w].varValue or 0)
        is_chip_w = val(use["WC"][w]) or val(use["FH"][w])
        if is_chip_w:
            true_ft[w + 1] = min(5, true_ft[w] + 1)
        else:
            used_w = tcount_w - hits_w
            true_ft[w + 1] = min(5, true_ft[w] - used_w + 1)

    # ---- running bank balance per week ----
    # Read directly from the solve's own bank[w] variable (real cash-flow
    # tracking - see build_and_solve's "real cash-flow budget tracking"
    # block) rather than re-deriving it here in Python: a naive replay
    # using sell_price[i] unconditionally for every sale would repeat the
    # exact stale-discount bug that block exists to fix (a rebought
    # original-squad player's SECOND sale isn't at their old discount).
    # bank_after[w] is the balance ONCE week w's own transfers are
    # applied - "this is your team/bank as it now stands" - matching how
    # the FT count below also reports usage against that week's OWN
    # allowance, not a carried-over pre-transfer figure.
    # max(0, ...): bank[w]'s own lowBound=0 already guarantees this, but
    # the LP relaxation can return a float a hair below zero (e.g.
    # -1e-12) - harmless numerically, but prints as an ugly "£-0.0m".
    bank_after = {w: max(0.0, sol["bank"][w].varValue) for w in weeks}
    first_sale = sol["first_sale"]

    for w in weeks:
        chips_active = [c for c in use if val(use[c][w])]
        gw_col = f"GW{w}"
        print("\n" + "=" * 60)
        print(f"GW{w}" + (f"   CHIP: {', '.join(chips_active)}" if chips_active else ""))

        ins = [i for i in P if val(sol["tin"][i][w])]
        outs = [i for i in P if val(sol["tout"][i][w])]
        ftv = true_ft[w]
        # round before any truthiness check - HiGHS/CBC can return a
        # tiny non-zero float (e.g. 1e-9) for a variable that's really 0,
        # which printed as a bogus "(-0)" hit-cost suffix otherwise.
        hitv = round(sol["hits"][w].varValue or 0)
        # "used/available" - matches FPLReview's own convention (e.g.
        # "1/1", "0/1", "2/2"; "3/2 (-4)" once transfers exceed the free
        # allowance) - shows how many transfers were spent against that
        # week's OWN banked allowance, not a running/cumulative count.
        used_str = f"{len(ins)}/{ftv:.0f}" + (f" (-{4 * hitv:.0f})" if hitv else "")
        if ins or outs:
            print(f"Transfers ({used_str}, bank: £{bank_after[w]:.1f}m):")
            for i in outs:
                # Real proceeds: the discounted sell_price ONLY on a true
                # first sale of an original-squad player - any other sale
                # (a rebought original, or a player bought during this
                # plan) is always at current market price, matching what
                # the solve's own bank tracking actually charges/credits.
                real_out_price = sell_price[i] if (i in first_sale and val(first_sale[i][w])) \
                    else players.loc[i, "price"]
                print(f"  OUT {players.loc[i, 'name']:20s} {real_out_price:.1f}")
            for i in ins:
                print(f"  IN  {players.loc[i, 'name']:20s} {players.loc[i, 'price']:.1f}")
        else:
            print(f"No transfers ({used_str}, bank: £{bank_after[w]:.1f}m)")

        lineup_idx = [i for i in P if val(sol["lineup"][i][w])]
        bench_idx = [i for i in P if val(sol["bench"][i][w])]
        cap = next(i for i in P if val(sol["captain"][i][w]))

        ldf = players.loc[lineup_idx].sort_values(["position", gw_col], ascending=[True, False])
        # bench: GK first, then the outfield 3 purely by score (not grouped by position)
        bench_gk = players.loc[[i for i in bench_idx if players.loc[i, "position"] == 1]]
        bench_out = players.loc[[i for i in bench_idx if players.loc[i, "position"] != 1]]
        bdf = pd.concat([bench_gk, bench_out.sort_values(gw_col, ascending=False)])

        vice = ldf.loc[ldf.index != cap, gw_col].idxmax()

        print("XI:")
        for _, r in ldf.iterrows():
            tag = " (C)" if r.name == cap else (" (V)" if r.name == vice else "")
            opp = opp_str(opponents, r['team'], w)
            print(f"  [{r['id']:4d}] {'GDMF'[r['position']-1]} {r['name']:20s} {r['team']:3s} vs {opp:12s} {r['price']:5.1f}  {r[gw_col]:5.2f}{tag}")
        print("Bench:")
        for _, r in bdf.iterrows():
            opp = opp_str(opponents, r['team'], w)
            print(f"  [{r['id']:4d}] {'GDMF'[r['position']-1]} {r['name']:20s} {r['team']:3s} vs {opp:12s} {r['price']:5.1f}  {r[gw_col]:5.2f}")

        xi_pts = sum(players.loc[i, gw_col] for i in lineup_idx)
        cap_mult = 2 if not val(use["TC"][w]) else 3
        cap_extra = players.loc[cap, gw_col] * (cap_mult - 1)
        bb_pts = sum(players.loc[i, gw_col] for i in bench_idx) if val(use["BB"][w]) else 0
        print(f"Projected: XI {xi_pts:.2f} + captain {cap_extra:.2f}"
              + (f" + bench boost {bb_pts:.2f}" if bb_pts else "")
              + (f" - hits {4 * hitv:.0f}" if hitv else ""))


if __name__ == "__main__":
    t0 = time.time()
    sync_team_from_fpl()
    players = load_players()
    report_squad_prices(players)
    sol = build_and_solve(players)
    report(players, sol)
    print(f"\nTotal time: {time.time() - t0:.1f}s")
