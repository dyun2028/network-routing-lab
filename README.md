# network-routing-lab

Small, tested Python models I wrote to learn how core IP routing and physical-layer link planning work.
No dependencies beyond the standard library (`pytest` for tests).

**Scope note:** these are simulations and reference calculators built for study. They are not production
routing software and are not a substitute for hands-on work with real routers, optics, or test equipment.

## What's in it

| Module | What it models |
|---|---|
| `routinglab/ospf.py` | Single-area OSPF: router LSAs with sequence numbers, flooding to a fixed point, two-way connectivity check, Dijkstra SPF with equal-cost multipath, cost from reference bandwidth, reconvergence after link failure |
| `routinglab/bgp.py` | BGP decision process (local-pref, AS-path length, origin, MED within the same neighbor AS, eBGP over iBGP, IGP metric, router-id), AS-path loop prevention, the iBGP no-readvertise rule, per-peer local-pref policy |
| `routinglab/optics.py` | Nominal 802.3 reach tables (1000BASE-SX/LX through 100GBASE-ER4), copper category limits (Cat5e/6/6A), and a fiber power-budget calculator (fiber, connector and splice loss vs. Tx power and Rx sensitivity) |

## Run it

```bash
python -m pytest -q          # 17 tests
python demo.py               # prints routing tables, a BGP policy change, and link budgets
```

## Example

```python
from routinglab.ospf import Network

n = Network()
for a, b in [("A", "B"), ("B", "D"), ("A", "C"), ("C", "D")]:
    n.connect(a, b, bandwidth_mbps=100)
n.converge()
n.routing_table("A")["D"]      # (2, ['B', 'C'])  -> two equal-cost paths

n.disconnect("B", "D"); n.converge()
n.routing_table("A")["D"]      # (2, ['C'])       -> reconverged
```

## Known simplifications

- OSPF: one area, point-to-point links only, no DR/BDR, no timers or LSA aging.
- BGP: synchronous rounds instead of sessions and timers; no route reflectors, communities, or confederations.
- Optics: loss and attenuation values are typical planning numbers; real designs must use datasheets.
