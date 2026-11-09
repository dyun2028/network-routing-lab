"""Single-area OSPF model: router LSAs, reliable-style flooding, and SPF with ECMP.

This is a study model of the link-state mechanics (LSDB, sequence numbers,
two-way connectivity check, Dijkstra SPF, equal-cost multipath). It does not
implement the wire protocol, DR/BDR election, or multiple areas.
"""
from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass

REFERENCE_BW_MBPS = 100  # classic OSPF default reference bandwidth


def ospf_cost(bandwidth_mbps: float, reference_mbps: float = REFERENCE_BW_MBPS) -> int:
    """Interface cost = reference bandwidth / interface bandwidth, minimum 1."""
    if bandwidth_mbps <= 0:
        raise ValueError("bandwidth must be positive")
    return max(1, int(reference_mbps // bandwidth_mbps))


@dataclass(frozen=True)
class Link:
    neighbor: str
    cost: int


@dataclass(frozen=True)
class LSA:
    """Router LSA: the origin router's directly attached links."""

    origin: str
    seq: int
    links: tuple[Link, ...]


class Router:
    def __init__(self, rid: str):
        self.rid = rid
        self.links: dict[str, int] = {}  # physical adjacencies: neighbor -> cost
        self.lsdb: dict[str, LSA] = {}
        self.seq = 0

    def originate(self) -> LSA:
        self.seq += 1
        lsa = LSA(self.rid, self.seq, tuple(Link(n, c) for n, c in sorted(self.links.items())))
        self.lsdb[self.rid] = lsa
        return lsa

    def receive(self, lsa: LSA) -> bool:
        """Install an LSA if it is newer than what we hold. True means 'flood it on'."""
        current = self.lsdb.get(lsa.origin)
        if current is not None and current.seq >= lsa.seq:
            return False
        self.lsdb[lsa.origin] = lsa
        return True

    def spf(self) -> dict[str, tuple[int, list[str]]]:
        """Dijkstra over the LSDB. Returns {dest: (cost, sorted first-hop neighbors)}.

        A link is usable only if both ends advertise it (two-way check), which is
        how OSPF avoids routing over half-dead adjacencies.
        """
        dist = {self.rid: 0}
        first_hops: dict[str, set[str]] = {self.rid: set()}
        heap = [(0, self.rid)]
        done: set[str] = set()
        while heap:
            d, u = heapq.heappop(heap)
            if u in done:
                continue
            done.add(u)
            lsa = self.lsdb.get(u)
            if lsa is None:
                continue
            for link in lsa.links:
                v = link.neighbor
                back = self.lsdb.get(v)
                if back is None or all(x.neighbor != u for x in back.links):
                    continue
                nd = d + link.cost
                hops = {v} if u == self.rid else first_hops[u]
                if v not in dist or nd < dist[v]:
                    dist[v] = nd
                    first_hops[v] = set(hops)
                    heapq.heappush(heap, (nd, v))
                elif nd == dist[v]:
                    first_hops[v] |= hops
        return {dst: (dist[dst], sorted(first_hops[dst])) for dst in dist if dst != self.rid}


class Network:
    def __init__(self) -> None:
        self.routers: dict[str, Router] = {}
        self._dirty: set[str] = set()

    def add_router(self, rid: str) -> Router:
        self.routers.setdefault(rid, Router(rid))
        self._dirty.add(rid)
        return self.routers[rid]

    def connect(self, a: str, b: str, bandwidth_mbps: float = 1000) -> int:
        cost = ospf_cost(bandwidth_mbps)
        ra, rb = self.add_router(a), self.add_router(b)
        ra.links[b] = cost
        rb.links[a] = cost
        self._dirty.update((a, b))
        return cost

    def disconnect(self, a: str, b: str) -> None:
        self.routers[a].links.pop(b, None)
        self.routers[b].links.pop(a, None)
        self._dirty.update((a, b))

    def converge(self) -> int:
        """Originate fresh LSAs for changed routers and flood to a fixed point.

        Returns the number of LSA transmissions, a rough measure of flooding cost.
        """
        messages = 0
        queue: deque[tuple[str, str | None, LSA]] = deque()
        for rid in sorted(self._dirty):
            lsa = self.routers[rid].originate()
            for n in self.routers[rid].links:
                queue.append((n, rid, lsa))
        self._dirty.clear()
        while queue:
            to, sender, lsa = queue.popleft()
            messages += 1
            router = self.routers[to]
            if router.receive(lsa):
                for n in router.links:
                    if n != sender:
                        queue.append((n, to, lsa))
        return messages

    def routing_table(self, rid: str) -> dict[str, tuple[int, list[str]]]:
        return self.routers[rid].spf()
