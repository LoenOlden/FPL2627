# The ONE expected-points calculation, used by project.py for BOTH outputs
# (projection.csv and final_player_data.py). Ported from FPLTest2's
# expectedpoints2.py with identical math, with two deliberate changes:
#   1. xmins is passed per gameweek (from xmins_by_gw) instead of one
#      season-wide number.
#   2. Team ratings come from team_ratings.py instead of local copies.
#
# Known intentional quirks preserved from the old model (do not "fix" casually):
#   - GK appearance divisor is 93 (review GK xmins cap ~93).
#   - CBIT/CBITR lambda is scaled by appearance ratio AND the final sum is
#     multiplied by appearance again - deliberate dampening for low-xmins players.
#   - Point values (4.16 CS, 6.24 DEF goal, ...) bake in a small bonus uplift.

from scipy.stats import poisson

from config import home_coefficient, away_coefficient
from team_ratings import (cbit_coef, cbitr_coef, team_coef_Att, team_coef_Def,
                          team_xg90, team_xgc90)


# ---------- Poisson helpers ----------

def poisson_cleansheet(lam):
    return poisson.pmf(0, lam)

def prob_conceding_2_or_3(lam):
    return poisson.pmf(2, lam) + poisson.pmf(3, lam)

def prob_conceding_4_or_5(lam):
    return poisson.pmf(4, lam) + poisson.pmf(5, lam)

def prob_conceding_6_plus(lam):
    return 1.0 - sum(poisson.pmf(k, lam) for k in range(6))

def prob_over_60(xmin):
    return 1 - poisson.cdf(59, mu=xmin)

def prob_3to5_saves(avg):
    return poisson.pmf(3, avg) + poisson.pmf(4, avg) + poisson.pmf(5, avg)

def prob_6to8_saves(avg):
    return poisson.pmf(6, avg) + poisson.pmf(7, avg) + poisson.pmf(8, avg)

def prob_9plus_saves(avg):
    return 1.0 - sum(poisson.pmf(k, avg) for k in range(9))

def prob_cbit_10plus(lam):
    return 1 - poisson.cdf(9, mu=lam)

def prob_cbitr_12plus(lam):
    return 1 - poisson.cdf(11, mu=lam)


# ---------- Shared sub-calculations ----------

def _lambda_xgc(player, opponent, reversecoeff):
    return ((player["TeamXGC90"] * opponent["TeamAttCoef"]
             + opponent["TeamXG90"] * player["TeamDefCoef"]) * reversecoeff) / 2

def _concede_penalty(lam):
    return (-1.027 * prob_conceding_2_or_3(lam)
            - 2.054 * prob_conceding_4_or_5(lam)
            - 3.08 * prob_conceding_6_plus(lam))

def _yellow(player, opponent, reversecoeff):
    return player["crdY"] * ((opponent["TeamAttCoef"] + 1) / 2) * reversecoeff


# ---------- Position models ----------
# Each takes xmins explicitly (per-GW value decided by the caller).

def goalkeeper_points(player, opponent, home_away_coeff, fix_prob, xmins):
    appearance = xmins / 93
    reversecoeff = 2 - home_away_coeff
    lam_xgc = _lambda_xgc(player, opponent, reversecoeff)

    cs_points = 4.16 * poisson_cleansheet(lam_xgc)
    over60 = prob_over_60(xmins)
    yellow = _yellow(player, opponent, reversecoeff)

    save_lam = player["saves90"] * opponent["TeamAttCoef"] * reversecoeff
    save_points = (1.02 * prob_3to5_saves(save_lam)
                   + 2.04 * prob_6to8_saves(save_lam)
                   + 3.06 * prob_9plus_saves(save_lam))

    total = cs_points + save_points + over60 + _concede_penalty(lam_xgc) - yellow + 1
    return total * appearance * fix_prob


def defender_points(player, opponent, home_away_coeff, fix_prob, xmins):
    appearance = xmins / 90
    reversecoeff = 2 - home_away_coeff
    lam_xgc = _lambda_xgc(player, opponent, reversecoeff)

    cs_points = 4.16 * poisson_cleansheet(lam_xgc)
    over60 = prob_over_60(xmins)
    yellow = _yellow(player, opponent, reversecoeff)

    goal_points = player["xG90"] * 6.24 * opponent["TeamDefCoef"] * home_away_coeff
    assist_points = player["xA90"] * 3.09 * opponent["TeamDefCoef"] * home_away_coeff

    dc_coef = (reversecoeff + 1.0) / 2
    cbit_lam = player["CBIT90"] * appearance * cbit_coef.get(opponent["team_name"], 1.0) * dc_coef
    dc_points = 2.01 * prob_cbit_10plus(cbit_lam)

    total = (cs_points + goal_points + assist_points + over60
             + _concede_penalty(lam_xgc) - yellow + dc_points + 1)
    return total * appearance * fix_prob


def midfielder_points(player, opponent, home_away_coeff, fix_prob, xmins):
    appearance = xmins / 90
    reversecoeff = 2 - home_away_coeff
    lam_xgc = _lambda_xgc(player, opponent, reversecoeff)

    cs_points = 1.0 * poisson_cleansheet(lam_xgc)
    over60 = prob_over_60(xmins)
    yellow = _yellow(player, opponent, reversecoeff)

    goal_points = player["xG90"] * 5.3 * opponent["TeamDefCoef"] * home_away_coeff
    assist_points = player["xA90"] * 3.09 * opponent["TeamDefCoef"] * home_away_coeff

    dc_coef = (reversecoeff + 1.0) / 2
    cbitr_lam = player["CBITR90"] * appearance * cbitr_coef.get(opponent["team_name"], 1.0) * dc_coef
    dc_points = 2.01 * prob_cbitr_12plus(cbitr_lam)

    total = cs_points + goal_points + assist_points + over60 - yellow + dc_points + 1
    return total * appearance * fix_prob


def forward_points(player, opponent, home_away_coeff, fix_prob, xmins):
    appearance = xmins / 90
    reversecoeff = 2 - home_away_coeff

    goal_points = player["xG90"] * 4.32 * opponent["TeamDefCoef"] * home_away_coeff
    assist_points = player["xA90"] * 3.09 * opponent["TeamDefCoef"] * home_away_coeff
    over60 = prob_over_60(xmins)
    yellow = _yellow(player, opponent, reversecoeff)

    dc_coef = (reversecoeff + 1.0) / 2
    cbitr_lam = player["CBITR90"] * appearance * cbitr_coef.get(opponent["team_name"], 1.0) * dc_coef
    dc_points = 2.01 * prob_cbitr_12plus(cbitr_lam)

    total = goal_points + assist_points + over60 + dc_points - yellow + 1
    return total * appearance * fix_prob


POSITION_CALCS = {1: goalkeeper_points, 2: defender_points, 3: midfielder_points, 4: forward_points}


def opponent_data(abbr):
    return {
        "team_name": abbr,
        "TeamXG90": team_xg90.get(abbr, 1),
        "TeamXGC90": team_xgc90.get(abbr, 1),
        "TeamAttCoef": team_coef_Att.get(abbr, 1),
        "TeamDefCoef": team_coef_Def.get(abbr, 1),
    }


def player_xmins_for_gw(player, gw):
    """Per-GW xmins when available, else the season-wide fallback."""
    by_gw = player.get("xmins_by_gw") or {}
    val = by_gw.get(str(gw))
    if val is None:
        return float(player.get("expected_minutes", 0.0))
    return float(val)


def fixture_points(player, opponent_abbr, is_home, fix_prob, gw):
    """Expected points for one player in one fixture."""
    calc = POSITION_CALCS.get(player["position"])
    if calc is None:
        return 0.0
    xmins = player_xmins_for_gw(player, gw)
    if xmins <= 0:
        return 0.0
    coeff = home_coefficient if is_home else away_coefficient
    return calc(player, opponent_data(opponent_abbr), coeff, fix_prob, xmins)
