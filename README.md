# Rajasthan day: dispatch and unit commitment

Synthetic day. Not an IEX extract. No transmission, no hydro, no outage.

Two models.

- `dispatch.py` — 24-hour linear dispatch. Plants are always available. The battery has a state of charge and chooses its hours.
- `unit_commitment.py` — the modeller version. On/off, minimum stable level, start cost, ramp, minimum up time, 12 MW upward reserve. Prices come from a linear programme with the commitment fixed.

Study note: `STUDY.md`.

## Unit commitment, the result to remember

Cost ₹36.6 lakh without the battery, ₹34.5 lakh with a 15 MW / 30 MWh battery, saving about ₹2.1 lakh. Gas starts once and runs 18:00–21:00. Coal and nuclear stay on all day. The battery discharges into the peak, including 9 MW at 19:00, and the 19:00 price stays ₹7,000. Noon price goes from zero to ₹400, because charging stops solar being spilled. At twice the solar build, noon is zero again.

## Run

```bash
pip install -r requirements.txt
python unit_commitment.py
python dispatch.py
```
