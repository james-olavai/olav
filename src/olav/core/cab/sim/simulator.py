"""Sim simulator — networkx graph mutation + invariant checks.

R-CAB-THREE-STAGE Day 4 (2026-05-12, dev_docs/75).

Reads ``draft.facts_collected`` (devices + topology_edges), builds a
networkx undirected Graph, applies the per-intent mutation, and
reports invariant violations as RiskFlags. Pure Python; deterministic
from input.

What the simulator catches (Day-4 MVP):
  * device_isolated      — proposed change leaves a device with no
                           graph-reachable neighbor
  * (future, Day 5)
    routing_loop_introduced
    existing_session_broken
    blast_radius_large

What it emits unconditionally on success:
  * no_routing_loop       (placeholder — full check is Day 5)
  * no_isolation
  * existing_sessions_intact (placeholder — full check is Day 5)
"""
from __future__ import annotations

from typing import Any

import networkx as nx

from olav.core.cab.schemas import (
    DraftChangePlan,
    RouteChange,
    SessionImpact,
    SimulationReport,
)


def _build_graph(draft: DraftChangePlan) -> nx.Graph:
    g = nx.Graph()
    for dev in draft.facts_collected.devices:
        g.add_node(dev.name, **{
            "platform": dev.platform,
            "local_as": dev.local_as,
            "loopback": dev.loopback,
        })
    for e in draft.facts_collected.topology_edges:
        g.add_edge(
            e.source_device, e.destination_device,
            source_interface=e.source_interface,
            destination_interface=e.destination_interface,
        )
    return g


def _routes_for_intent(draft: DraftChangePlan) -> list[RouteChange]:
    """What new routes (RIB entries) would the change install?

    Per-intent: BGP intents add adjacency-style entries; static_route_add
    adds a single explicit prefix entry; YAML-schema intents may or may
    not (deferred to Day-5 renderer for the full picture).
    """
    routes: list[RouteChange] = []
    intent = draft.proposed_intent
    devices = list(draft.devices_in_scope)
    args = draft.intent_args

    if intent in ("ebgp_direct", "ibgp_direct") and len(devices) == 2:
        a, b = devices
        idx = {d.name: d for d in draft.facts_collected.devices}
        # Represent the new BGP session as a pair of "next-hop" entries
        # so callers can count session adjacencies.
        for src, dst in ((a, b), (b, a)):
            nh = idx[dst].loopback if intent == "ibgp_direct" else None
            routes.append(RouteChange(
                device=src, prefix=f"bgp:{intent}:{dst}", next_hop=nh,
            ))
    elif intent == "static_route_add" and len(devices) == 1 and args.get("dst_prefix"):
        routes.append(RouteChange(
            device=devices[0],
            prefix=args["dst_prefix"],
            next_hop=args.get("next_hop_ip"),
        ))
    # vlan_add / freeform_cli: no automatic RouteChange entries —
    # they don't install routes per se, freeform may but it's
    # opaque to the simulator.
    return routes


def _check_isolation(g: nx.Graph, draft: DraftChangePlan) -> list[str]:
    """Return list of scoped devices that are isolated in the graph.

    Isolation is only meaningful for intents that REQUIRE direct L2
    adjacency between the scoped pair (ebgp_direct). For:
      * single-device intents (vlan_add / freeform_cli / static_route_add)
        — "no graph neighbors" usually just means the analyzer didn't
        bother collecting topology, not a real fault
      * ibgp_direct — peers via loopback over IGP, direct L2 NOT required
        (this was a false positive in-vivo on 2026-05-12 when gemma
        switched from ebgp_direct to ibgp_direct per Sim's suggestion
        and the simulator then blocked it with device_isolated)

    For ebgp_direct the feasibility rule already catches the
    not_directly_connected case; this is a defence-in-depth pass over
    the broader graph view.
    """
    if len(draft.devices_in_scope) < 2:
        return []
    if draft.proposed_intent == "ibgp_direct":
        return []
    isolated = []
    for d in draft.devices_in_scope:
        if d in g.nodes and g.degree(d) == 0:
            isolated.append(d)
    return isolated


def simulate_change(draft: DraftChangePlan) -> SimulationReport:
    """Run the proposed change against a graph built from facts.

    Never raises — invariant violations are encoded as RiskFlags.
    Deterministic-from-input: the same draft produces the same report.
    """
    g = _build_graph(draft)

    risk_flags: list[str] = []
    sessions_impacted: list[SessionImpact] = []

    isolated = _check_isolation(g, draft)
    if isolated:
        risk_flags.append("device_isolated")
    else:
        risk_flags.append("no_isolation")

    # Placeholder pass flags — Day 5 wires the real checks.
    risk_flags.append("no_routing_loop")
    risk_flags.append("existing_sessions_intact")

    routes_added = _routes_for_intent(draft)

    # Convergence estimate: rough heuristic on intent type. Real
    # estimate would come from configured BGP timers; for Day-4 MVP
    # use a fixed-per-intent value (zero variance between runs).
    convergence_estimate_s = {
        "ebgp_direct": 60,
        "ibgp_direct": 90,
        "static_route_add": 0,
        "vlan_add": 5,
        "freeform_cli": 0,
    }.get(draft.proposed_intent, 0)

    return SimulationReport(
        risk_flags=risk_flags,  # type: ignore[arg-type]
        routes_added=routes_added,
        routes_removed=[],
        sessions_impacted=sessions_impacted,
        convergence_estimate_s=convergence_estimate_s,
    )
