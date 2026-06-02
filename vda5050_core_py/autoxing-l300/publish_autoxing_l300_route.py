#!/usr/bin/env python3
"""Publish GameTL Autoxing L300 demo route order and verify adapter state via MQTT."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
ORDER_TOPIC = "uagv/v2/Manufacturer/S001/order"
STATE_TOPIC = "uagv/v2/Manufacturer/S001/state"
ORDER_ID = "gametl_autoxing_l300"
ROUTE_TIMEOUT_S = 600.0

# VDA5050 §6.6.1 / §6.6.3.1: the first node of an order must be "trivially
# reachable" — the AGV is on it or within its deviation range. We satisfy this
# two ways at once (belt-and-suspenders, no either/or branch on reachability):
#   1. Unconditional: the first PUBLISHED node always carries this deviation
#      radius (spec §6.6.3.1 option 2), so the order is reachable even when no
#      pose is available.
#   2. Best-effort: when the AGV's current pose is known from its State, we
#      prepend a node at that pose (spec §6.6.3.1 option 1). The deviation also
#      absorbs pose staleness — State cadence is only guaranteed <=30s (§6.10),
#      so the cached pose may lag the robot's true position.
# 1.0 m covers localization jitter; the robot is idle when we publish (no active
# order), so staleness drift is ~0 in practice.
FIRST_NODE_DEVIATION_M = 1.0

# How long to wait for the AGV to report an initialized agvPosition before
# falling back to deviation-only. 35s > the §6.10 worst-case 30s state
# heartbeat; the 1Hz adapter normally fills this in ~1s.
POSE_TIMEOUT_S = 35.0

# Autoxing active map (GET /chassis/current-map via spellbook get_current_map):
# {
#   "id": 15,
#   "uid": "69fb0226fe07afec2a1e2c67",
#   "map_name": "LargeARTC",
#   "create_time": 1778057765,
#   "map_version": 0,
#   "overlays_version": 2
# }
MAP_ID = "LargeARTC"

ORDER = {
    "headerId": 1,
    "timestamp": "",
    "version": "2.0.0",
    "manufacturer": "Manufacturer",
    "serialNumber": "S001",
    "orderId": ORDER_ID,
    "orderUpdateId": 0,
    "nodes": [
        {
            "nodeId": "node_table",
            "sequenceId": 0,
            "released": True,
            "actions": [],
            "nodePosition": {"x": -11.0, "y": 1.2, "mapId": MAP_ID},
        },
        {
            "nodeId": "node_row",
            "sequenceId": 2,
            "released": True,
            "actions": [],
            "nodePosition": {"x": -11.0, "y": 3.0, "mapId": MAP_ID},
        },
        {
            "nodeId": "node_west",
            "sequenceId": 4,
            "released": True,
            "actions": [],
            "nodePosition": {"x": -16.0, "y": 3.0, "mapId": MAP_ID},
        },
        {
            "nodeId": "node_east",
            "sequenceId": 6,
            "released": True,
            "actions": [],
            "nodePosition": {"x": -6.0, "y": 3.0, "mapId": MAP_ID},
        },
    ],
    # Edges are intentionally trajectory-free. The AutoXing L300 is a
    # freely-navigating vehicle (VDA5050 §3, §6.1.1): it plans its own path
    # between nodes, so master control must omit the optional `trajectory`
    # edge attribute and send only fields the AGV's factsheet supports. The
    # robot does local navigation / obstacle avoidance itself
    # (autoxing_bridge.dispatch_move -> POST /chassis/moves). Do NOT add a
    # `trajectory` here; when the C++/Python master lands it must apply the
    # same guard for this AGV.
    "edges": [
        {
            "edgeId": "edge_table_row",
            "sequenceId": 1,
            "released": True,
            "startNodeId": "node_table",
            "endNodeId": "node_row",
            "actions": [],
        },
        {
            "edgeId": "edge_row_west",
            "sequenceId": 3,
            "released": True,
            "startNodeId": "node_row",
            "endNodeId": "node_west",
            "actions": [],
        },
        {
            "edgeId": "edge_west_east",
            "sequenceId": 5,
            "released": True,
            "startNodeId": "node_west",
            "endNodeId": "node_east",
            "actions": [],
        },
    ],
}


def has_position(state: dict) -> bool:
    """True when the AGV's State carries an initialized agvPosition with x/y."""
    pos = state.get("agvPosition")
    if not isinstance(pos, dict) or not pos.get("positionInitialized"):
        return False
    return isinstance(pos.get("x"), (int, float)) and isinstance(
        pos.get("y"), (int, float)
    )


def build_order(current_pose: dict | None) -> tuple[dict, int, int, str, int]:
    """Build the order payload.

    The first published node ALWAYS carries ``allowedDeviationXY`` so the order
    is trivially reachable regardless of branch (VDA5050 §6.6.3.1 option 2).
    When ``current_pose`` is available, additionally prepend ``node_current`` at
    that pose plus a connecting edge, shifting every existing sequenceId by +2
    (§6.6.3.1 option 1).

    Returns ``(order, node_count, edge_count, last_node_id, last_node_seq)`` so
    the verification predicates can assert against the graph actually built.
    """
    msg = copy.deepcopy(ORDER)
    msg["headerId"] = 4
    msg["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    if current_pose is not None:
        old_first_id = msg["nodes"][0]["nodeId"]
        # Make room for the prepended node (seq 0) + edge (seq 1).
        for node in msg["nodes"]:
            node["sequenceId"] += 2
        for edge in msg["edges"]:
            edge["sequenceId"] += 2
        msg["nodes"].insert(
            0,
            {
                "nodeId": "node_current",
                "sequenceId": 0,
                "released": True,
                "actions": [],
                "nodePosition": {
                    "x": float(current_pose["x"]),
                    "y": float(current_pose["y"]),
                    "mapId": MAP_ID,
                    "allowedDeviationXY": FIRST_NODE_DEVIATION_M,
                },
            },
        )
        msg["edges"].insert(
            0,
            {
                "edgeId": "edge_current_table",
                "sequenceId": 1,
                "released": True,
                "startNodeId": "node_current",
                "endNodeId": old_first_id,
                "actions": [],
            },
        )
    else:
        # No pose: the existing first node is the entry point — stamp it.
        msg["nodes"][0]["nodePosition"]["allowedDeviationXY"] = FIRST_NODE_DEVIATION_M

    last = msg["nodes"][-1]
    return (
        msg,
        len(msg["nodes"]),
        len(msg["edges"]),
        last["nodeId"],
        last["sequenceId"],
    )


def make_accepted(n_nodes: int, n_edges: int):
    def accepted(state: dict) -> bool:
        return (
            state.get("orderId") == ORDER_ID
            and state.get("orderUpdateId", 0) == 0
            and len(state.get("nodeStates") or []) == n_nodes
            and len(state.get("edgeStates") or []) == n_edges
        )

    return accepted


def make_route_done(last_node_id: str, last_node_seq: int):
    def route_done(state: dict) -> bool:
        return (
            state.get("lastNodeId") == last_node_id
            and state.get("lastNodeSequenceId", 0) == last_node_seq
        )

    return route_done


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-route", action="store_true")
    parser.add_argument("--broker", default=BROKER)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument(
        "--route-timeout",
        type=float,
        default=ROUTE_TIMEOUT_S,
        help=f"seconds to wait for route completion (default: {ROUTE_TIMEOUT_S})",
    )
    parser.add_argument(
        "--pose-timeout",
        type=float,
        default=POSE_TIMEOUT_S,
        help=(
            "seconds to wait for an initialized agvPosition before falling back "
            f"to deviation-only (default: {POSE_TIMEOUT_S})"
        ),
    )
    args = parser.parse_args()

    latest = {}
    updated = threading.Event()

    def on_message(_c, _u, msg):
        try:
            latest.clear()
            latest.update(json.loads(msg.payload.decode()))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        updated.set()

    client = mqtt.Client()
    client.on_message = on_message
    client.connect(args.broker, args.port, 60)
    client.subscribe(STATE_TOPIC)
    client.loop_start()
    time.sleep(0.3)

    def wait_for(check, timeout, label):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            updated.wait(0.25)
            updated.clear()
            if latest and check(latest):
                print(f"{label}: PASS")
                return True
        print(f"{label}: FAIL", file=sys.stderr)
        if latest:
            print(json.dumps(latest, indent=2), file=sys.stderr)
        return False

    # Phase 0: acquire the AGV's current pose so the first node is trivially
    # reachable. Event-driven (paho's network thread fires on_message on every
    # State publish); not a fixed-rate poll. Falls back to deviation-only.
    print(f"Phase 0: waiting for AGV pose (timeout {args.pose_timeout:.0f}s) ...")
    current_pose: dict | None = None
    if wait_for(has_position, args.pose_timeout, "Phase 0"):
        current_pose = latest.get("agvPosition")
        print(
            f"Pose acquired -> prepending node_current at "
            f"({current_pose.get('x')}, {current_pose.get('y')})"
        )
    else:
        print(
            f"No pose within {args.pose_timeout:.0f}s -> relying on deviation-only "
            f"({FIRST_NODE_DEVIATION_M} m) on the first node",
            file=sys.stderr,
        )

    order, n_nodes, n_edges, last_node_id, last_node_seq = build_order(current_pose)

    print(
        f"Publishing order to {ORDER_TOPIC} "
        f"({n_nodes} nodes, {n_edges} edges) ..."
    )
    client.publish(ORDER_TOPIC, json.dumps(order))

    print("Phase A: waiting for order acceptance ...")
    if not wait_for(make_accepted(n_nodes, n_edges), 5.0, "Phase A"):
        client.loop_stop()
        return 1

    if not args.wait_route:
        client.loop_stop()
        print("Done. Use --wait-route for full navigation check.")
        return 0

    print(f"Phase B: waiting for route completion (timeout {args.route_timeout}s) ...")
    ok = wait_for(make_route_done(last_node_id, last_node_seq), args.route_timeout, "Phase B")
    client.loop_stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
