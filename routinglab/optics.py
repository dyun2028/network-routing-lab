"""Fiber and copper cabling reference plus an optical link-budget calculator.

Reach figures are the nominal IEEE 802.3 maximum reaches for common Ethernet
PHYs. Attenuation and connector/splice losses are typical *planning* values;
always use the transceiver and cable datasheets for a real design.
"""
from __future__ import annotations

from dataclasses import dataclass

# Typical planning attenuation in dB/km at the operating wavelength.
FIBER_ATTENUATION_DB_KM = {
    ("OM3", 850): 3.5,
    ("OM4", 850): 3.5,
    ("OS2", 1310): 0.4,
    ("OS2", 1550): 0.3,
}
CONNECTOR_LOSS_DB = 0.5  # per mated connector pair (TIA allows up to 0.75)
SPLICE_LOSS_DB = 0.1  # per fusion splice

# Nominal maximum reach in meters by PHY and fiber grade.
PHY_REACH_M = {
    "1000BASE-SX": {"OM2": 550},
    "1000BASE-LX": {"OS2": 5000},
    "10GBASE-SR": {"OM3": 300, "OM4": 400},
    "10GBASE-LR": {"OS2": 10_000},
    "10GBASE-ER": {"OS2": 40_000},
    "25GBASE-SR": {"OM3": 70, "OM4": 100},
    "40GBASE-SR4": {"OM3": 100, "OM4": 150},
    "100GBASE-SR4": {"OM3": 70, "OM4": 100},
    "100GBASE-LR4": {"OS2": 10_000},
    "100GBASE-ER4": {"OS2": 40_000},
}
PHY_WAVELENGTH_NM = {
    "10GBASE-SR": 850, "25GBASE-SR": 850, "40GBASE-SR4": 850, "100GBASE-SR4": 850,
    "10GBASE-LR": 1310, "100GBASE-LR4": 1310, "1000BASE-LX": 1310,
    "10GBASE-ER": 1550, "100GBASE-ER4": 1550,
}

# Maximum channel length in meters and the best Ethernet speed in Gb/s that each
# copper category supports over it (twisted pair).
COPPER_REACH = {
    "Cat5e": {1: 100},
    "Cat6": {1: 100, 10: 55},
    "Cat6A": {1: 100, 10: 100},
}
PASSIVE_DAC_MAX_M = 5  # passive direct-attach copper, typical limit at 10G-25G


def phy_reach_m(phy: str, fiber: str) -> int:
    try:
        return PHY_REACH_M[phy][fiber]
    except KeyError:
        raise ValueError(f"{phy} is not specified over {fiber}") from None


def copper_ok(category: str, speed_gbps: int, length_m: float) -> bool:
    limits = COPPER_REACH[category]
    if speed_gbps not in limits:
        return False
    return length_m <= limits[speed_gbps]


@dataclass(frozen=True)
class LinkBudget:
    loss_db: float
    budget_db: float
    margin_db: float

    @property
    def ok(self) -> bool:
        return self.margin_db >= 0


def link_budget(
    length_m: float,
    fiber: str,
    wavelength_nm: int,
    tx_power_dbm: float,
    rx_sensitivity_dbm: float,
    connectors: int = 2,
    splices: int = 0,
    safety_margin_db: float = 3.0,
) -> LinkBudget:
    """Power-budget check: (Tx power - Rx sensitivity) vs. fiber, connector, splice loss."""
    attenuation = FIBER_ATTENUATION_DB_KM[(fiber, wavelength_nm)]
    loss = (length_m / 1000) * attenuation + connectors * CONNECTOR_LOSS_DB + splices * SPLICE_LOSS_DB
    budget = tx_power_dbm - rx_sensitivity_dbm
    return LinkBudget(round(loss, 2), round(budget, 2), round(budget - loss - safety_margin_db, 2))
