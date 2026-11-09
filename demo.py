from routinglab.bgp import BGPNetwork
from routinglab.optics import link_budget, phy_reach_m
from routinglab.ospf import Network


def ospf_demo() -> None:
    n = Network()
    for a, b in [("A", "B"), ("B", "D"), ("A", "C"), ("C", "D")]:
        n.connect(a, b, bandwidth_mbps=100)
    msgs = n.converge()
    print(f"OSPF converged with {msgs} LSA transmissions")
    print("A's table:", n.routing_table("A"))
    n.disconnect("B", "D")
    n.converge()
    print("after B-D fails, A's table:", n.routing_table("A"))


def bgp_demo() -> None:
    n = BGPNetwork()
    for name, asn, rid in [("R1", 65001, "1.1.1.1"), ("R2", 65002, "2.2.2.2"), ("R3", 65003, "3.3.3.3")]:
        n.add_speaker(name, asn, rid)
    for a, b in [("R1", "R2"), ("R2", "R3"), ("R1", "R3")]:
        n.peer(a, b)
    n.speakers["R1"].originate("192.0.2.0/24")
    n.run()
    print("R3 default choice:", n.speakers["R3"].loc_rib["192.0.2.0/24"].as_path)
    n.speakers["R3"].local_pref_in["R2"] = 300
    n.run()
    print("R3 after local-pref 300 on R2:", n.speakers["R3"].loc_rib["192.0.2.0/24"].as_path)


def optics_demo() -> None:
    print("10GBASE-SR over OM4 max reach (m):", phy_reach_m("10GBASE-SR", "OM4"))
    lb = link_budget(10_000, "OS2", 1310, tx_power_dbm=-3, rx_sensitivity_dbm=-14.4)
    print("10 km OS2 link:", lb, "OK" if lb.ok else "FAILS")


if __name__ == "__main__":
    ospf_demo()
    bgp_demo()
    optics_demo()
