import pytest

from routinglab.bgp import BGPNetwork, Route, best_path
from routinglab.optics import copper_ok, link_budget, phy_reach_m
from routinglab.ospf import Network, ospf_cost


# ---------- OSPF ----------
def test_cost_from_bandwidth():
    assert ospf_cost(10) == 10
    assert ospf_cost(100) == 1
    assert ospf_cost(1000) == 1  # floor at 1 with the 100 Mb/s reference
    assert ospf_cost(1000, reference_mbps=100_000) == 100


def square():
    n = Network()
    for a, b in [("A", "B"), ("B", "D"), ("A", "C"), ("C", "D")]:
        n.connect(a, b, 100)
    n.converge()
    return n


def test_ecmp_over_equal_cost_paths():
    table = square().routing_table("A")
    assert table["D"] == (2, ["B", "C"])


def test_reconverges_after_link_failure():
    n = square()
    n.disconnect("B", "D")
    n.converge()
    assert n.routing_table("A")["D"] == (2, ["C"])
    assert n.routing_table("B")["D"][0] == 3  # B -> A -> C -> D


def test_lsdbs_synchronized():
    n = square()
    dbs = [{k: v.seq for k, v in r.lsdb.items()} for r in n.routers.values()]
    assert all(d == dbs[0] for d in dbs)


def test_partition_removes_unreachable_routes():
    n = Network()
    n.connect("A", "B", 100)
    n.connect("C", "D", 100)
    n.converge()
    assert "C" not in n.routing_table("A")


def test_two_way_check_ignores_one_sided_link():
    n = Network()
    n.connect("A", "B", 100)
    n.converge()
    # B stops advertising A but A still lists B: SPF at A must not use the link.
    n.routers["B"].links.pop("A")
    n.routers["B"].originate()
    n.routers["A"].receive(n.routers["B"].lsdb["B"])
    assert "B" not in n.routing_table("A")


# ---------- BGP ----------
def r(**kw):
    base = dict(prefix="10.0.0.0/8", next_hop="x", as_path=(65001,), router_id="1.1.1.1")
    base.update(kw)
    return Route(**base)


def test_local_pref_beats_as_path_length():
    a = r(local_pref=200, as_path=(1, 2, 3), router_id="2.2.2.2")
    b = r(local_pref=100, as_path=(1,))
    assert best_path([a, b]) is a


def test_shorter_as_path_wins():
    a = r(as_path=(1, 2))
    b = r(as_path=(3,), router_id="2.2.2.2")
    assert best_path([a, b]) is b


def test_med_only_compared_within_same_neighbor_as():
    a = r(as_path=(10,), med=50, router_id="3.3.3.3")
    b = r(as_path=(10,), med=10, router_id="4.4.4.4")
    c = r(as_path=(20,), med=0, router_id="9.9.9.9")  # different neighbor AS: MED not compared with a/b
    assert best_path([a, b, c]).router_id == "4.4.4.4"  # b ties c on MED group, lower router-id wins


def test_ebgp_preferred_over_ibgp_then_igp_metric():
    ib = r(ebgp=False, igp_metric=1, router_id="1.1.1.1")
    eb = r(ebgp=True, igp_metric=50, router_id="2.2.2.2")
    assert best_path([ib, eb]) is eb
    near = r(ebgp=False, igp_metric=5, router_id="9.9.9.9")
    far = r(ebgp=False, igp_metric=20, router_id="1.1.1.1")
    assert best_path([far, near]) is near


def test_lowest_router_id_tiebreak():
    a = r(router_id="10.0.0.9")
    b = r(router_id="10.0.0.10")
    assert best_path([a, b]) is a  # numeric compare, not string compare


def build_triangle():
    n = BGPNetwork()
    n.add_speaker("R1", 65001, "1.1.1.1")
    n.add_speaker("R2", 65002, "2.2.2.2")
    n.add_speaker("R3", 65003, "3.3.3.3")
    for a, b in [("R1", "R2"), ("R2", "R3"), ("R1", "R3")]:
        n.peer(a, b)
    n.speakers["R1"].originate("192.0.2.0/24")
    return n


def test_propagation_and_loop_prevention():
    n = build_triangle()
    n.run()
    assert n.speakers["R2"].loc_rib["192.0.2.0/24"].as_path == (65001,)
    assert n.speakers["R3"].loc_rib["192.0.2.0/24"].as_path == (65001,)
    # R1 never accepts its own prefix back via another AS
    assert n.speakers["R1"].loc_rib["192.0.2.0/24"].as_path == ()


def test_local_pref_policy_steers_traffic():
    n = build_triangle()
    n.speakers["R3"].local_pref_in["R2"] = 300  # R3 prefers anything learned from R2
    n.run()
    route = n.speakers["R3"].loc_rib["192.0.2.0/24"]
    assert route.next_hop == "R2" and route.as_path == (65002, 65001)


def test_ibgp_does_not_readvertise_ibgp_routes():
    n = BGPNetwork()
    n.add_speaker("E", 65001, "1.1.1.1")
    n.add_speaker("A", 65002, "2.2.2.2")
    n.add_speaker("B", 65002, "3.3.3.3")
    n.add_speaker("C", 65002, "4.4.4.4")
    n.peer("E", "A")
    n.peer("A", "B")
    n.peer("B", "C")  # chain, not a full mesh
    n.speakers["E"].originate("198.51.100.0/24")
    n.run()
    assert "198.51.100.0/24" in n.speakers["B"].loc_rib
    assert "198.51.100.0/24" not in n.speakers["C"].loc_rib  # why iBGP needs a full mesh or RRs


# ---------- Optics / cabling ----------
def test_reach_table():
    assert phy_reach_m("10GBASE-SR", "OM3") == 300
    assert phy_reach_m("10GBASE-LR", "OS2") == 10_000
    with pytest.raises(ValueError):
        phy_reach_m("10GBASE-LR", "OM3")


def test_copper_limits():
    assert copper_ok("Cat6A", 10, 100)
    assert not copper_ok("Cat6", 10, 80)
    assert not copper_ok("Cat5e", 10, 10)


def test_link_budget_pass_and_fail():
    ok = link_budget(10_000, "OS2", 1310, tx_power_dbm=-3, rx_sensitivity_dbm=-14.4)
    assert ok.ok and ok.loss_db == pytest.approx(5.0)
    bad = link_budget(40_000, "OS2", 1310, tx_power_dbm=-3, rx_sensitivity_dbm=-14.4, splices=8)
    assert not bad.ok
