#!/usr/bin/env python3
"""GameTL POC client: vda5050_core_py Adapter + Autoxing REST/WebSocket I/O.

Implements diagram steps ⑤–⑨: on_navigate → POST /chassis/moves → poll pose/status
→ set_agv_position/set_driving → node_reached. Node iteration stays in C++.

Usage::

    # Terminal 1 — AGV adapter + Autoxing bridge
    python3 vda5050_core_py/autoxing-l300/example_autoxing_client.py

    # Terminal 2 — publish demo order (requires mosquitto)
    python3 vda5050_core_py/autoxing-l300/publish_autoxing_l300_route.py --wait-route

Prerequisites: spellbook CONSTANTS.yml configured; robot map loaded and localized.

Active Autoxing map (``get_current_map``) — VDA5050 ``nodePosition.mapId`` must use ``map_name``:

.. code-block:: json

    {
      "id": 15,
      "uid": "69fb0226fe07afec2a1e2c67",
      "map_name": "LargeARTC",
      "create_time": 1778057765,
      "map_version": 0,
      "overlays_version": 2
    }

Map id flows: order JSON ``mapId`` → ``node.node_position.map_id`` → published state
``agvPosition.mapId``. Autoxing navigate uses x/y only; map must already be loaded on robot.

``on_navigate`` must return quickly — blocking work runs on a worker thread so C++
``suspend_for<NodeAckUpdate>`` can receive ``node_reached`` and advance to the next node.
"""

# TODO & State of the current example
# - NodePosition w/o theta, fixed map_id

from __future__ import annotations

import argparse
import json
import sys
import threading
import traceback
from pathlib import Path

import vda5050_core_py as vda

from autoxing_bridge import (
    dispatch_move,
    poll_pose_and_planning,
    tracked_pose_to_agv_position,
    wait_for_arrival,
)

CONFIG = {
    "broker": "tcp://localhost:1883",
    "client_id": "autoxing_l300_agv",
    "interface": "uagv",
    "protocol_version": "2.0.0",
    "manufacturer": "Manufacturer",
    "serial_number": "S001",
    "poll_interval": 1.0,
    "nav_timeout": 300.0,
    "map_id": "LargeARTC",
}


# The topology map the master loads; its first node is treated as "home".
HOME_MAP_PATH = Path(__file__).parent / "large_artc_map.json"


def _home_node_xy() -> tuple[float, float]:
    """Read the home node (first node of the loaded map) coordinates.

    "Home" == the first entry in ``large_artc_map.json``'s ``nodes`` (node_table).
    Falls back to the origin (0, 0) if the map can't be read or is malformed, so
    dry-run mode never hard-fails on a missing/typo'd map file.
    """
    try:
        with HOME_MAP_PATH.open() as f:
            home = json.load(f)["nodes"][0]
        return float(home["x"]), float(home["y"])
    except (OSError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"[dry-run] Could not read home node from {HOME_MAP_PATH}: {exc}; "
            f"falling back to origin (0, 0)",
            file=sys.stderr,
        )
        return 0.0, 0.0


def _home_agv_position(map_id: str) -> vda.AGVPosition:
    """Build an initialized AGVPosition at the map's home node for dry-run mode.

    Lets the adapter publish a valid agvPosition without any robot/bridge I/O,
    so a master sees the AGV parked on a real map node (node_table) — which
    makes the first order node trivially reachable (VDA5050 §6.6.1) instead of
    sitting at an off-map origin.
    """
    x, y = _home_node_xy()
    agv = vda.AGVPosition()
    agv.position_initialized = True
    agv.x = x
    agv.y = y
    agv.theta = 0.0
    agv.map_id = map_id
    return agv


def _publish_initial_pose(
    nav: vda.NavigationManager, map_id: str, *, dry_run: bool = False
) -> None:
    """Poll the robot's pose once and seed the published State's agvPosition.

    The adapter otherwise only learns the pose during navigation (mirror_pose
    below), so an idle robot publishes no agvPosition. A master (or the demo
    publisher) needs an initialized pose up front to make the first order node
    trivially reachable (VDA5050 §6.6.3.1). Best-effort: a robot/bridge failure
    is logged and ignored — the publisher falls back to a deviation-only node.
    """
    # Dry run: no robot to poll, so seed the pose at the map's home node.
    if dry_run:
        agv = _home_agv_position(map_id)
        nav.set_agv_position(agv)
        print(
            f"[dry-run] Initial pose seeded at home node "
            f"({agv.x}, {agv.y}) map={map_id!r}",
            file=sys.stderr,
        )
        return
    try:
        pose_msg, _planning = poll_pose_and_planning()
        agv = tracked_pose_to_agv_position(pose_msg, map_id=map_id)
        if agv.position_initialized:
            nav.set_agv_position(agv)
            print(
                f"Initial pose seeded: ({agv.x}, {agv.y}) map={map_id!r}",
                file=sys.stderr,
            )
        else:
            print("Initial pose unavailable (not localized?)", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 — best-effort startup seed
        print(f"Initial pose poll failed: {exc}", file=sys.stderr)


def _drive_to_node(
    node: vda.Node,
    nav: vda.NavigationManager,
    *,
    nav_timeout: float,
    poll_interval: float,
    dry_run: bool = False,
) -> None:
    """Blocking Autoxing navigate + poll; calls node_reached on the worker thread."""
    try:
        pos = node.node_position
        print(
            f"Navigate to {node.node_id} "
            f"({pos.x}, {pos.y}, theta={pos.theta}) map={pos.map_id!r}",
            file=sys.stderr,
        )
        nav.set_driving(True)

        # Dry run: skip the Autoxing REST move + pose polling entirely. Publish a
        # zero pose and immediately report the node as reached so the C++ node
        # iteration advances exactly as it would with a real robot — but with no
        # physical motion and no bridge I/O.
        if dry_run:
            nav.set_agv_position(_home_agv_position(pos.map_id or ""))
            nav.set_driving(False)
            print(f"  [dry-run] node_reached({node.node_id})", file=sys.stderr)
            nav.node_reached(node)
            return

        move = dispatch_move(node)
        if move is None:
            nav.set_driving(False)
            raise RuntimeError(f"Autoxing navigate failed for node {node.node_id}")

        move_id = move.get("id")
        print(f"  move id={move_id}", file=sys.stderr)

        map_id = pos.map_id or ""

        def mirror_pose(agv: vda.AGVPosition, move_state: str | None) -> None:
            if agv.position_initialized:
                nav.set_agv_position(agv)
            if move_state:
                print(f"  move_state={move_state}", file=sys.stderr)

        terminal = wait_for_arrival(
            pos.x,
            pos.y,
            move_id=move_id,
            map_id=map_id,
            timeout_s=nav_timeout,
            poll_interval_s=poll_interval,
            on_poll=mirror_pose,
        )

        nav.set_driving(False)
        if terminal != "succeeded":
            raise RuntimeError(
                f"Move to {node.node_id} ended with state {terminal!r}"
            )

        print(f"  node_reached({node.node_id})", file=sys.stderr)
        nav.node_reached(node)
    except Exception as exc:
        nav.set_driving(False)
        print(
            f"Navigation failed for {node.node_id}: {exc}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run the adapter without a physical robot or Autoxing bridge: "
            "publish an all-zero agvPosition and immediately mark each node as "
            "reached. Lets you exercise the MQTT/order flow with no hardware."
        ),
    )
    args = parser.parse_args()
    dry_run = args.dry_run
    if dry_run:
        print("[dry-run] No robot I/O — poses published as zero.", file=sys.stderr)

    mqtt = vda.create_default_mqtt_client(CONFIG["broker"], CONFIG["client_id"])
    protocol = vda.ProtocolAdapter.make(
        mqtt,
        CONFIG["interface"],
        CONFIG["protocol_version"],
        CONFIG["manufacturer"],
        CONFIG["serial_number"],
    )
    adapter = vda.Adapter.make(protocol)
    nav = adapter.navigation_manager()

    def on_navigate(node: vda.Node) -> None:
        threading.Thread(
            target=_drive_to_node,
            args=(node, nav),
            kwargs={
                "nav_timeout": CONFIG["nav_timeout"],
                "poll_interval": CONFIG["poll_interval"],
                "dry_run": dry_run,
            },
            daemon=True,
        ).start()

    adapter.on_navigate(on_navigate)
    _publish_initial_pose(nav, CONFIG["map_id"], dry_run=dry_run)
    adapter.start()
    print(
        f"Adapter started ({CONFIG['interface']}/v2/"
        f"{CONFIG['manufacturer']}/{CONFIG['serial_number']})",
        file=sys.stderr,
    )
    vda.run_until_signal(adapter)
    return 0


if __name__ == "__main__":
    sys.exit(main())

