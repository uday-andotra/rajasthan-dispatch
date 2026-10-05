# Power-market modelling: study note for this repo

This note is the subject, tied to the two scripts in the folder. Read it once, then run the scripts, then read the result section again. Synthetic data throughout. Nothing here is an IEX day.

## 1. What the model is for

A fundamental power-market model answers which plants run, and what the price is, in each hour. It is not a regression on past prices. Demand, plant capacity, fuel cost, wind and solar output and a few constraints go in. A solver minimises the cost of meeting demand. The price falls out as the cost of serving one more megawatt.

Aurora, AFRY and Wood Mackenzie sell the output of models like this: hourly prices, capture prices for solar, battery revenue, the effect of a new plant. The analyst seat runs cases. The modeller seat writes or configures the constraints.

## 2. Merit order, the linear programme, the unit commitment

Three versions of the same idea, in increasing order of what the solver is allowed to decide.

Merit order. Sort plants by variable cost. Fill demand. The last plant sets the price. `dispatch.py` is this idea, solved as a linear programme so the battery can choose its hours. Plants are always available. A coal unit can run at 0.5 MW. That is the fiction.

Linear programme. Continuous variables only. Generation between zero and capacity, battery charge and discharge, a state of charge. Fast, and the price is a true dual. It cannot switch a plant off in a way that respects a minimum stable level.

Unit commitment. The modeller version, in `unit_commitment.py`. On and off are binary. A unit has a minimum stable level, a start cost, a ramp and a minimum time on. This is a mixed-integer programme. CBC solves it. The price is not taken from the integer solve. Commitment is fixed, the remaining problem is a linear programme, and the price is the dual of that. Say this if asked. A mixed-integer solve does not have a clean hourly price.

## 3. The price

For each hour the balance is

$$
\sum_i p_{i,t} + d^{\mathrm{out}}_t - d^{\mathrm{in}}_t = D_t
$$

$p$ is generation, $d^{\mathrm{out}}$ is battery discharge, $d^{\mathrm{in}}$ is charge, $D$ is demand. The price is the dual of this row: how much the day's cost rises if demand in that hour rises by 1 MW. If the last megawatt is gas at ₹7,000, the price is ₹7,000. If solar has covered demand and a megawatt is being spilled, the price is zero.

Zero is the result to refuse until you know why. In this repo it means curtailment. No reserve and no must-run is forcing a thermal plant to stay marginal.

## 4. The stack used here

| Plant | Variable cost, INR/MWh | Capacity, MW | Minimum, MW | Start cost | Min hours on |
|---|---:|---:|---:|---:|---:|
| Solar | 0 | 60, shaped by a noon profile | — | — | — |
| Wind | 0 | 20, mild daily shape | — | — | — |
| Nuclear | 400 | 25 | 18 | ₹2,00,000 | 8 |
| Coal | 3,500 | 55 | 22 | ₹80,000 | 4 |
| Gas | 7,000 | 40 | 8 | ₹12,000 | 1 |

Battery: 15 MW, 30 MWh, 90% one-way efficiency. Reserve, in the unit commitment only: 12 MW of upward headroom every hour, from committed thermal capacity not yet used, plus unused battery discharge. The day wraps, so nuclear and coal enter already on. That is why their start count is zero. Do not describe it as a cold start.

Demand is synthetic: a sine through the day plus an evening peak from 18:00 to 21:00, floored at 70 MW.

## 5. What the two scripts actually find

Continuous dispatch, `dispatch.py`. Cost ₹34.4 lakh without the battery, ₹33.6 lakh with it, saving about ₹72,000. The battery charges at 05:00, 12:00 and 15:00, all at ₹3,500, and discharges at 18:00, 20:00 and 21:00, at ₹7,000. It does not discharge at 19:00. The tank is empty. Gas volume falls. The 19:00 price stays ₹7,000.

Unit commitment, `unit_commitment.py`. Cost ₹36.6 lakh without the battery, ₹34.5 lakh with it, saving about ₹2.1 lakh, start costs included. Gas starts once and runs 18:00–21:00 only. Coal and nuclear stay on all day, because of the minimum up time and the wrap. The battery charges 09:00–12:00 and discharges 15 MW at 18:00, 9 MW at 19:00 and 3 MW at 20:00. The 19:00 price still stays ₹7,000. Gas remains the marginal plant. The hour that moves is noon: zero without the battery, ₹400 with it. Charging soaks solar that would otherwise be spilled, and nuclear sets the price.

At twice the solar build, noon is zero again in both models. The tank is smaller than the surplus. That zero is curtailment.

The sentence. A battery earns the coal-to-gas spread only in the hours it can still cover. Size the tank against the length of the peak, not against the noon surplus. It did not cut the peak price. It stopped the model throwing noon power away.

## 6. Capture price, the number clients ask for

Baseload price is the average across all hours. A solar capture price is the average price in the hours solar actually generates, weighted by its output. Solar generates at noon, when its own output has pushed the price down, so the capture price is below the baseload price. That gap is cannibalisation. This repo does not print it. If asked, say you would weight the hourly price by solar generation, and that a zero noon price makes the capture price collapse even if the evening price is ₹7,000.

## 7. GAMS, PLEXOS, and this folder

The solver is CBC, called from PuLP, and HiGHS, called from SciPy for the linear programme and for the prices. GAMS is a language that sends the same kind of programme to CPLEX or Gurobi. PLEXOS is a commercial application that builds the unit commitment for you from a plant database. This repo is the formulation, written out. It is not PLEXOS. In an interview say you have not used GAMS or PLEXOS, and that the commitment here is Python and CBC.

## 8. What a reviewer will poke

The wrap. Nuclear never starts because the day is circular. A real model has an initial status.

No transmission. Rajasthan solar and a Delhi evening peak are not the same node. A line limit can strand the noon surplus and leave the evening on gas even with a bigger battery.

No outage, no hydro, no must-run policy. Any of these can move the gas commitment.

Reserve is a flat 12 MW. A real reserve is a percentage of demand plus the largest unit.

Prices from the fixed-commitment linear programme ignore the start cost. The start is a lump, already paid. Do not quote ₹7,000 as including the start.

## 9. How to talk about it

One minute. I built a 24-hour unit commitment in Python. Coal and nuclear stay on, gas starts once for the evening peak, a 15 MW battery discharges into that peak and does not clear gas off the margin. Noon price goes from zero to the nuclear cost because the battery absorbs spilled solar. At twice the solar build, noon is zero again. No transmission, no hydro, commitment wraps.

Do not claim an India stack, an IEX back-test, or a client price path.

## 10. What to read next, in this order

The dual of a demand balance, any linear-programming note, until the price-as-marginal-cost point is obvious. Then unit commitment: minimum stable level, start cost, minimum up time. Then why a mixed-integer programme has no clean price, and why practitioners fix the commitment and re-solve. Then capture price and cannibalisation. Stop there. GAMS syntax and PLEXOS screenshots will not move this application. A second node would.
