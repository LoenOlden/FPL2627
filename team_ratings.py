# Team strength ratings - the file you hand-edit during pre-season / mid-season.
# Values carried over from 2025/26 end-of-season (FPLTest2/expectedpoints2.py).
# Update xg90/xgc90/saves90/CBIT tables from fbref/understat, then the
# Att/Def coefficients below are DERIVED automatically - don't edit those by hand.

team_xg90 = {
    "MCI": 1.995, "ARS": 1.927, "MUN": 1.755, "LIV": 1.71, "CHE": 1.599,
    "BHA": 1.54, "BOU": 1.516, "AVL": 1.461, "BRE": 1.446, "NEW": 1.429,
    "TOT": 1.303, "LEE": 1.288, "NFO": 1.287, "CRY": 1.277, "FUL": 1.264,
    "EVE": 1.257, "SUN": 1.124, "IPS": 1.031, "COV": 1.024, "HUL": 0.877,
}

team_xgc90 = {
    "ARS": 0.817, "MCI": 1.04, "MUN": 1.216, "LIV": 1.23, "BHA": 1.311,
    "CHE": 1.345, "AVL": 1.35, "BOU": 1.368, "TOT": 1.388, "EVE": 1.391,
    "NFO": 1.393, "LEE": 1.403, "BRE": 1.413, "NEW": 1.434, "CRY": 1.447,
    "FUL": 1.453, "SUN": 1.519, "COV": 1.744, "IPS": 1.863, "HUL": 1.985,
}

saves90 = {
    "ARS": 1.61, "MCI": 2.34, "MUN": 2.39, "LIV": 2.61, "BHA": 2.71,
    "AVL": 3.00, "CHE": 2.76, "TOT": 2.45, "BOU": 2.87, "EVE": 2.61,
    "NEW": 2.97, "CRY": 2.82, "FUL": 2.58, "BRE": 2.79, "LEE": 2.66,
    "NFO": 2.82, "SUN": 3.11, "COV": 3.08, "IPS": 3.27, "HUL": 3.58,
}

# Defensive-contribution opponent multipliers (how many CBIT/CBITR actions a
# team concedes relative to average). Edit these from your fbref CBIT data.
cbit_coef = {
    "MCI": 1.14, "AVL": 1.11, "TOT": 1.10, "NEW": 1.07, "LIV": 1.07,
    "CHE": 1.04, "MUN": 1.03, "NFO": 1.03, "BHA": 1.02, "ARS": 1.01,
    "IPS": 0.98, "BRE": 0.98, "COV": 0.97, "EVE": 0.97, "BOU": 0.96,
    "FUL": 0.94, "HUL": 0.92, "LEE": 0.91, "CRY": 0.88, "SUN": 0.87
}

cbitr_coef = {
    "MCI": 1.14, "AVL": 1.11, "TOT": 1.10, "NEW": 1.07, "LIV": 1.07,
    "CHE": 1.04, "MUN": 1.03, "NFO": 1.03, "BHA": 1.02, "ARS": 1.01,
    "IPS": 0.98, "BRE": 0.98, "COV": 0.97, "EVE": 0.97, "BOU": 0.96,
    "FUL": 0.94, "HUL": 0.92, "LEE": 0.91, "CRY": 0.88, "SUN": 0.87
}

# ---- Derived coefficients (attack/defence strength vs league average) ----
_avg_xg = sum(team_xg90.values()) / len(team_xg90)
_avg_xgc = sum(team_xgc90.values()) / len(team_xgc90)

team_coef_Att = {t: round(v / _avg_xg, 3) for t, v in team_xg90.items()}
team_coef_Def = {t: round(v / _avg_xgc, 3) for t, v in team_xgc90.items()}

if __name__ == "__main__":
    def report(name, d):
        total = sum(d.values())
        print(f'{name}: n={len(d)} sum={total:.3f} avg={total/len(d):.4f}')

    report('xg90', team_xg90)
    report('xgc90', team_xgc90)
    report('cbit_coef', cbit_coef)
    report('cbitr_coef', cbitr_coef)
