"""BGP model: best-path selection and eBGP/iBGP propagation between speakers.

Implements the standard decision process steps that matter for most designs
(local-pref, AS-path length, origin, MED within the same neighbor AS, eBGP over
iBGP, lowest IGP metric, lowest router-id), AS-path loop prevention, and the
iBGP no-readvertise rule. It is a study model: no TCP sessions, timers,
communities, route reflectors, or confederations.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, replace

ORIGIN_IGP, ORIGIN_EGP, ORIGIN_INCOMPLETE = 0, 1, 2


@dataclass(frozen=True)
class Route:
    prefix: str
    next_hop: str
    as_path: tuple[int, ...] = ()
    local_pref: int = 100
    origin: int = ORIGIN_IGP
    med: int = 0
    ebgp: bool = True  # learned over eBGP (or locally originated)
    igp_metric: int = 0
    router_id: str = "0.0.0.0"

    @property
    def neighbor_as(self) -> int | None:
        return self.as_path[0] if self.as_path else None


def _keep_min(routes: list[Route], key) -> list[Route]:
    best = min(key(r) for r in routes)
    return [r for r in routes if key(r) == best]


def best_path(routes: list[Route]) -> Route:
    """Pick the best route among candidates for one prefix."""
    if not routes:
        raise ValueError("no candidate routes")
    cands = list(routes)
    cands = _keep_min(cands, lambda r: -r.local_pref)
    cands = _keep_min(cands, lambda r: len(r.as_path))
    cands = _keep_min(cands, lambda r: r.origin)
    # MED is only comparable between routes from the same neighboring AS.
    min_med: dict[int | None, int] = {}
    for r in cands:
        min_med[r.neighbor_as] = min(min_med.get(r.neighbor_as, r.med), r.med)
    cands = [r for r in cands if r.med == min_med[r.neighbor_as]]
    cands = _keep_min(cands, lambda r: 0 if r.ebgp else 1)
    cands = _keep_min(cands, lambda r: r.igp_metric)
    cands = _keep_min(cands, lambda r: int(ipaddress.IPv4Address(r.router_id)))
    return cands[0]


class Speaker:
    def __init__(self, name: str, asn: int, router_id: str):
        self.name, self.asn, self.router_id = name, asn, router_id
        self.originated: dict[str, Route] = {}
        self.local_pref_in: dict[str, int] = {}  # peer name -> local-pref set on import
        self.rib_in: dict[tuple[str, str], Route] = {}  # (prefix, peer) -> route
        self.loc_rib: dict[str, Route] = {}

    def originate(self, prefix: str) -> None:
        self.originated[prefix] = Route(prefix, self.name, (), router_id=self.router_id)

    def candidates(self, prefix: str) -> list[Route]:
        out = [r for (p, _), r in self.rib_in.items() if p == prefix]
        if prefix in self.originated:
            out.append(self.originated[prefix])
        return out

    def decide(self) -> None:
        prefixes = {p for p, _ in self.rib_in} | set(self.originated)
        self.loc_rib = {p: best_path(self.candidates(p)) for p in prefixes}


class BGPNetwork:
    def __init__(self) -> None:
        self.speakers: dict[str, Speaker] = {}
        self.sessions: list[tuple[str, str]] = []

    def add_speaker(self, name: str, asn: int, router_id: str) -> Speaker:
        self.speakers[name] = Speaker(name, asn, router_id)
        return self.speakers[name]

    def peer(self, a: str, b: str) -> None:
        self.sessions.append((a, b))

    def _export(self, sender: Speaker, receiver: Speaker, route: Route, learned_ibgp: bool) -> Route | None:
        ibgp = sender.asn == receiver.asn
        if ibgp:
            if learned_ibgp:  # iBGP-learned routes are not re-advertised to iBGP peers
                return None
            return replace(route, ebgp=False, router_id=sender.router_id)
        if receiver.asn in route.as_path:  # AS-path loop prevention
            return None
        lp = receiver.local_pref_in.get(sender.name, 100)
        return Route(
            route.prefix, sender.name, (sender.asn,) + route.as_path,
            local_pref=lp, origin=route.origin, med=0, ebgp=True,
            router_id=sender.router_id,
        )

    def run(self, max_rounds: int = 64) -> int:
        """Synchronous rounds until no best path changes. Returns rounds used."""
        for rounds in range(1, max_rounds + 1):
            new_in: dict[str, dict[tuple[str, str], Route]] = {n: {} for n in self.speakers}
            for a, b in self.sessions:
                for s, r in ((self.speakers[a], self.speakers[b]), (self.speakers[b], self.speakers[a])):
                    for prefix, best in s.loc_rib.items():
                        learned_ibgp = (not best.ebgp) and prefix not in s.originated
                        out = self._export(s, r, best, learned_ibgp)
                        if out is not None:
                            new_in[r.name][(prefix, s.name)] = out
            before = {n: dict(s.loc_rib) for n, s in self.speakers.items()}
            for n, s in self.speakers.items():
                s.rib_in = new_in[n]
                s.decide()
            if all(before[n] == s.loc_rib for n, s in self.speakers.items()) and rounds > 1:
                return rounds
        raise RuntimeError("BGP did not converge (possible policy oscillation)")
