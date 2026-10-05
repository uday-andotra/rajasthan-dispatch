"""24-hour cost-minimising dispatch with a battery state of charge.

Synthetic day. Not an IEX extract, not a unit-commitment model, no transmission.
The battery chooses when to charge. It is not told the hours.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

HOURS = np.arange(24)
# Evening peak added by hand so the gas hours are obvious.
DEMAND = np.clip(
    80 + 25 * np.sin((HOURS - 8) / 24 * 2 * np.pi) + 18 * ((HOURS >= 18) & (HOURS <= 21)),
    70,
    None,
)
SOLAR_CF = np.where(
    (HOURS >= 6) & (HOURS <= 18),
    np.clip(np.sin((HOURS - 6) / 12 * np.pi), 0, None),
    0.0,
)
WIND_CF = 0.35 + 0.15 * np.cos((HOURS - 2) / 24 * 2 * np.pi)

PLANTS = [
    ("solar", 0, 60),
    ("wind", 0, 20),
    ("nuclear", 400, 25),
    ("coal", 3500, 55),
    ("gas", 7000, 40),
]
NAMES = [name for name, _, _ in PLANTS]
COST = {name: cost for name, cost, _ in PLANTS}
CAP = {name: cap for name, _, cap in PLANTS}

# 15 MW inverter, 30 MWh tank, 90% one-way efficiency.
POWER = 15.0
ENERGY = 30.0
ETA = 0.9


def solve(solar_scale: float = 1.0, battery: bool = True):
    n, t_count = 8, 24
    objective = np.zeros(n * t_count)
    bounds = []
    for t in range(t_count):
        avail = [
            CAP["solar"] * SOLAR_CF[t] * solar_scale,
            CAP["wind"] * WIND_CF[t],
            CAP["nuclear"],
            CAP["coal"],
            CAP["gas"],
        ]
        for i, name in enumerate(NAMES):
            objective[t * n + i] = COST[name]
            bounds.append((0, float(avail[i])))
        bounds += [
            (0, POWER if battery else 0),
            (0, POWER if battery else 0),
            (0, ENERGY if battery else 0),
        ]

    balance = []
    balance_rhs = []
    for t in range(t_count):
        row = np.zeros(n * t_count)
        row[t * n : t * n + 5] = 1
        row[t * n + 5] = -1  # charge adds to load
        row[t * n + 6] = 1   # discharge serves load
        balance.append(row)
        balance_rhs.append(float(DEMAND[t]))

    soc = []
    soc_rhs = []
    for t in range(t_count):
        row = np.zeros(n * t_count)
        row[t * n + 7] = 1
        row[((t - 1) % t_count) * n + 7] = -1
        row[t * n + 5] = -ETA
        row[t * n + 6] = 1 / ETA
        soc.append(row)
        soc_rhs.append(0.0)

    res = linprog(
        objective,
        A_eq=np.vstack([balance, soc]),
        b_eq=np.array(balance_rhs + soc_rhs),
        bounds=bounds,
        method="highs",
    )
    if not res.success:
        raise RuntimeError(res.message)
    dispatch = res.x.reshape(t_count, n)
    price = res.eqlin.marginals[:t_count]
    return dispatch, price, float(res.fun)


def hours_on(dispatch, column: int, price) -> list[tuple[int, float, float]]:
    return [
        (int(t), round(float(dispatch[t, column]), 1), round(float(price[t]), 1))
        for t in range(24)
        if dispatch[t, column] > 0.2
    ]


def main() -> None:
    base, base_price, base_cost = solve(battery=False)
    with_bat, bat_price, bat_cost = solve(battery=True)
    doubled, doubled_price, doubled_cost = solve(solar_scale=2.0, battery=True)

    print(f"Cost, no battery:     {base_cost:,.0f} INR")
    print(f"Cost, with battery:   {bat_cost:,.0f} INR")
    print(f"Saving:               {base_cost - bat_cost:,.0f} INR")
    print(f"Noon price:           {base_price[12]:,.0f} -> {bat_price[12]:,.0f}")
    print(f"19:00 price:          {base_price[19]:,.0f} -> {bat_price[19]:,.0f}")
    print(f"Charge hours (h, MW, price):  {hours_on(with_bat, 5, bat_price)}")
    print(f"Discharge hours (h, MW, price): {hours_on(with_bat, 6, bat_price)}")
    print(
        f"Solar x2 noon price {doubled_price[12]:,.0f}, "
        f"solar used {doubled[12, 0]:.1f} MW, cost {doubled_cost:,.0f}"
    )
    print(
        "The battery charges on coal at 3,500 and discharges into gas at 7,000. "
        "It does not discharge at 19:00, because the tank is already empty by then. "
        "A zero noon price at 2x solar is curtailment, not a price discovery."
    )


if __name__ == "__main__":
    main()
