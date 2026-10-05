"""24-hour unit commitment. Modeller-grade relative to the merit-order sort.

Thermal units have a minimum stable level, a start cost, a ramp and a minimum
up time. A reserve constraint must be covered by committed headroom plus the
battery. Commitment is a MIP. Prices are the duals of the demand balance after
the on/off decisions are fixed, so the price is still the cost of one more MW.
Synthetic day. No transmission.
"""

from __future__ import annotations

import pulp
import numpy as np

HOURS = list(range(24))
DEMAND = np.clip(
    80 + 25 * np.sin((np.array(HOURS) - 8) / 24 * 2 * np.pi)
    + 18 * ((np.array(HOURS) >= 18) & (np.array(HOURS) <= 21)),
    70,
    None,
)
SOLAR_CF = np.where(
    (np.array(HOURS) >= 6) & (np.array(HOURS) <= 18),
    np.clip(np.sin((np.array(HOURS) - 6) / 12 * np.pi), 0, None),
    0.0,
)
WIND_CF = 0.35 + 0.15 * np.cos((np.array(HOURS) - 2) / 24 * 2 * np.pi)

# min stable, ramp, start cost INR, min up time hours
THERMAL = {
    "nuclear": {"cost": 400, "cap": 25, "min": 18, "ramp": 5, "start": 200_000, "min_up": 8},
    "coal": {"cost": 3500, "cap": 55, "min": 22, "ramp": 18, "start": 80_000, "min_up": 4},
    "gas": {"cost": 7000, "cap": 40, "min": 8, "ramp": 40, "start": 12_000, "min_up": 1},
}
SOLAR_CAP = 60.0
WIND_CAP = 20.0
POWER, ENERGY, ETA = 15.0, 30.0, 0.9
RESERVE = 12.0  # MW of upward reserve in every hour


def _solver():
    """Prefer a native CBC. PuLP's bundled binary is Intel-only and fails on Apple Silicon."""
    import shutil

    for candidate in (shutil.which("cbc"), "/opt/homebrew/bin/cbc", "/usr/local/bin/cbc"):
        if candidate:
            return pulp.COIN_CMD(path=candidate, msg=0, timeLimit=30)
    return pulp.PULP_CBC_CMD(msg=0, timeLimit=30)


def solve(solar_scale: float = 1.0, battery: bool = True, reserve: bool = True):
    m = pulp.LpProblem("uc", pulp.LpMinimize)
    on, gen, start = {}, {}, {}
    for name, p in THERMAL.items():
        for t in HOURS:
            on[name, t] = pulp.LpVariable(f"on_{name}_{t}", cat="Binary")
            gen[name, t] = pulp.LpVariable(f"g_{name}_{t}", lowBound=0, upBound=p["cap"])
            start[name, t] = pulp.LpVariable(f"st_{name}_{t}", cat="Binary")

    solar = {t: pulp.LpVariable(f"sol_{t}", lowBound=0) for t in HOURS}
    wind = {t: pulp.LpVariable(f"wnd_{t}", lowBound=0) for t in HOURS}
    ch = {t: pulp.LpVariable(f"ch_{t}", lowBound=0, upBound=POWER if battery else 0) for t in HOURS}
    dis = {t: pulp.LpVariable(f"dis_{t}", lowBound=0, upBound=POWER if battery else 0) for t in HOURS}
    soc = {t: pulp.LpVariable(f"soc_{t}", lowBound=0, upBound=ENERGY if battery else 0) for t in HOURS}

    fuel = pulp.lpSum(THERMAL[n]["cost"] * gen[n, t] for n in THERMAL for t in HOURS)
    starts = pulp.lpSum(THERMAL[n]["start"] * start[n, t] for n in THERMAL for t in HOURS)
    m += fuel + starts

    for t in HOURS:
        m += (
            pulp.lpSum(gen[n, t] for n in THERMAL) + solar[t] + wind[t] + dis[t] - ch[t]
            == float(DEMAND[t])
        )
        m += solar[t] <= SOLAR_CAP * float(SOLAR_CF[t]) * solar_scale
        m += wind[t] <= WIND_CAP * float(WIND_CF[t])
        for n, p in THERMAL.items():
            m += gen[n, t] >= p["min"] * on[n, t]
            m += gen[n, t] <= p["cap"] * on[n, t]
            prev = on[n, (t - 1) % 24]
            m += start[n, t] >= on[n, t] - prev
            # ramp on output, and a start may jump to min stable
            m += gen[n, t] - gen[n, (t - 1) % 24] <= p["ramp"] + p["min"] * start[n, t]
            m += gen[n, (t - 1) % 24] - gen[n, t] <= p["ramp"] + p["cap"] * start[n, (t + 1) % 24]
            if p["min_up"] > 1:
                window = [on[n, (t + k) % 24] for k in range(p["min_up"])]
                m += pulp.lpSum(window) >= p["min_up"] * start[n, t]
        m += soc[t] == soc[(t - 1) % 24] + ETA * ch[t] - dis[t] / ETA
        if reserve:
            headroom = pulp.lpSum((THERMAL[n]["cap"] * on[n, t] - gen[n, t]) for n in THERMAL)
            battery_room = (POWER - dis[t]) if battery else 0
            m += headroom + battery_room >= RESERVE

    status = m.solve(_solver())
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(pulp.LpStatus[status])

    commitment = {n: [int(round(on[n, t].value())) for t in HOURS] for n in THERMAL}
    generation = {n: [gen[n, t].value() for t in HOURS] for n in THERMAL}
    generation["solar"] = [solar[t].value() for t in HOURS]
    generation["wind"] = [wind[t].value() for t in HOURS]
    charge = [ch[t].value() for t in HOURS]
    discharge = [dis[t].value() for t in HOURS]
    starts_n = {n: sum(int(round(start[n, t].value() or 0)) for t in HOURS) for n in THERMAL}
    cost = pulp.value(m.objective)
    prices = _prices(commitment, solar_scale, battery, charge, discharge)
    return {
        "cost": cost,
        "commitment": commitment,
        "generation": generation,
        "charge": charge,
        "discharge": discharge,
        "starts": starts_n,
        "prices": prices,
    }


def _prices(commitment, solar_scale, battery, charge, discharge):
    """LP with commitment fixed. Dual of demand balance is the price."""
    from scipy.optimize import linprog

    names = list(THERMAL)
    n = 8
    T = 24
    objective = np.zeros(n * T)
    bounds = []
    for t in HOURS:
        for name in names:
            p = THERMAL[name]
            on = commitment[name][t]
            objective[t * n + names.index(name)] = p["cost"]
            bounds.append((p["min"] * on, p["cap"] * on if on else 0))
        objective[t * n + 3] = 0
        objective[t * n + 4] = 0
        bounds.append((0, SOLAR_CAP * float(SOLAR_CF[t]) * solar_scale))
        bounds.append((0, WIND_CAP * float(WIND_CF[t])))
        bounds.append((0, POWER if battery else 0))
        bounds.append((0, POWER if battery else 0))
        bounds.append((0, ENERGY if battery else 0))
    Aeq, beq = [], []
    for t in HOURS:
        row = np.zeros(n * T)
        row[t * n : t * n + 5] = 1
        row[t * n + 5] = -1
        row[t * n + 6] = 1
        Aeq.append(row)
        beq.append(float(DEMAND[t]))
    for t in HOURS:
        row = np.zeros(n * T)
        row[t * n + 7] = 1
        row[((t - 1) % T) * n + 7] = -1
        row[t * n + 5] = -ETA
        row[t * n + 6] = 1 / ETA
        Aeq.append(row)
        beq.append(0.0)
    res = linprog(objective, A_eq=np.array(Aeq), b_eq=np.array(beq), bounds=bounds, method="highs")
    if not res.success:
        return [None] * 24
    return list(res.eqlin.marginals[:T])


def main():
    base = solve(battery=False)
    bat = solve(battery=True)
    solar = solve(solar_scale=2.0, battery=True)
    print(f"Cost no battery {base['cost']:,.0f}  starts {base['starts']}")
    print(f"Cost battery    {bat['cost']:,.0f}  starts {bat['starts']}")
    print(f"Saving {base['cost'] - bat['cost']:,.0f}")
    print("Commitment coal ", "".join(str(x) for x in bat["commitment"]["coal"]))
    print("Commitment gas  ", "".join(str(x) for x in bat["commitment"]["gas"]))
    print("Commitment nuc  ", "".join(str(x) for x in bat["commitment"]["nuclear"]))
    dis_h = [(t, round(bat["discharge"][t], 1)) for t in HOURS if bat["discharge"][t] > 0.2]
    ch_h = [(t, round(bat["charge"][t], 1)) for t in HOURS if bat["charge"][t] > 0.2]
    print("charge", ch_h)
    print("discharge", dis_h)
    print(f"19:00 price no bat {base['prices'][19]:,.0f}  with bat {bat['prices'][19]:,.0f}")
    print(f"noon price no bat {base['prices'][12]:,.0f}  with bat {bat['prices'][12]:,.0f}")
    print(f"solar x2 noon price {solar['prices'][12]:,.0f}  19:00 {solar['prices'][19]:,.0f}")
    print(f"solar x2 starts {solar['starts']}")


if __name__ == "__main__":
    main()