#!/usr/bin/env python3
"""Example VDA5050 master webserver (FastAPI + Swagger).

The FMS-side counterpart to ``example_autoxing_client.py``. It drives the bound
``VDA5050Master`` over MQTT:

    Browser --HTTP--> this server --VDA5050Master.assign_order--> MQTT
            --> vda5050 adapter (example_autoxing_client.py) --> AutoXing L300

One order endpoint:

  POST /orders/route   assigns the hardcoded demo route as a VDA5050 Order
                       (node → edge → node …) and delivers it over MQTT.

Routing here is the hardcoded demo route (later: RMF2 MAPF upstream). This
server only validates / assigns / delivers; it does not plan routes.

Run with uv (from this folder). fastapi/uvicorn are declared in the PEP 723
block below, so uv provisions an isolated env on first run. The vda5050_core_py
binding is a colcon-built C extension, so source the ROS workspace first to put
it on PYTHONPATH (uv inherits PYTHONPATH; --python 3.10 matches the binding's
ABI)::

    source /opt/ros/humble/setup.bash
    source ../../install/setup.bash         # exports vda5050_core_py on PYTHONPATH
    uv run --python 3.10 example_master_webserver.py
    # then open http://127.0.0.1:8000/docs

Prerequisites for orders to actually publish: a running MQTT broker (mosquitto)
and a ready AGV (example_autoxing_client.py + robot). assign_order runs a
readiness pre-flight (ONLINE + AUTOMATIC + position-initialized); without a live
AGV the endpoint returns AGV_OFFLINE / AGV_NO_STATE_YET rather than publishing.
"""

# /// script
# requires-python = ">=3.10,<3.11"
# dependencies = [
#     "fastapi>=0.110",
#     "uvicorn>=0.29",
#     "rich>=13",
# ]
# ///

from __future__ import annotations

from pathlib import Path
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from rich.console import Console
from rich.pretty import pprint
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

import vda5050_core_py as vda

# Diagnostics on stderr, default style red (not a property of sys.stderr itself).
stderr_console = Console(stderr=True, style="bold red")

# ===== Configuration (matches example_autoxing_client.py) =====
BROKER = "tcp://localhost:1883"
CLIENT_ID = "example_master"
INTERFACE = "uagv"
PROTOCOL_VERSION = "2.0.0"
MANUFACTURER = "Manufacturer"
SERIAL_NUMBER = "S001"
MAP_ID = "LargeARTC"

# Demo route (same coordinates as publish_autoxing_l300_route.py): a list of
# (node_id, x, y). Edges connect consecutive nodes. The robot is freely
# navigating, so no trajectory is sent (§6.1.1) — it plans its own path.
ROUTE = [
    ("node_table", -11.0, 1.2),
    ("node_row", -11.0, 3.0),
    ("node_west", -16.0, 3.0),
    ("node_east", -6.0, 3.0),
]


# ===== Order building (mirrors publish_autoxing_l300_route.build_order) =====
def _node(node_id: str, seq: int, x: float, y: float) -> vda.Node:
    pos = vda.NodePosition()
    pos.x = x
    pos.y = y
    pos.map_id = MAP_ID
    node = vda.Node()
    node.node_id = node_id
    node.sequence_id = seq
    node.released = True
    node.node_position = pos
    return node


def _edge_id(i: int) -> str:
    """Stable edge id connecting ROUTE node ``i`` to ``i + 1``."""
    return f"edge_{ROUTE[i][0]}_{ROUTE[i + 1][0]}"


def _edge(edge_id: str, seq: int, start: str, end: str) -> vda.Edge:
    edge = vda.Edge()
    edge.edge_id = edge_id
    edge.sequence_id = seq
    edge.start_node_id = start
    edge.end_node_id = end
    edge.released = True
    return edge


def route_diagram() -> str:
    """Render the demo route as ``node --edge--> node --edge--> …`` for docs."""
    parts = [ROUTE[0][0]]
    for i in range(len(ROUTE) - 1):
        parts.append(f"--{_edge_id(i)}-->")
        parts.append(ROUTE[i + 1][0])
    return " ".join(parts)


def build_route_order(order_id: str = "example_master_route") -> vda.Order:
    """Build the hardcoded demo route as a ``vda.Order``.

    Emits the 4-node route with interleaved sequence ids (nodes 0,2,4,6; edges
    1,3,5) and released nodes/edges. The robot navigates freely, so no
    trajectory is sent (§6.1.1) — it plans its own path between map nodes.
    """
    nodes = [_node(node_id, 2 * i, x, y) for i, (node_id, x, y) in enumerate(ROUTE)]
    edges = [
        _edge(_edge_id(i), 2 * i + 1, ROUTE[i][0], ROUTE[i + 1][0])
        for i in range(len(ROUTE) - 1)
    ]

    order = vda.Order()
    order.order_id = order_id
    order.order_update_id = 0
    order.header.version = PROTOCOL_VERSION
    order.header.manufacturer = MANUFACTURER
    order.header.serial_number = SERIAL_NUMBER
    order.nodes = nodes
    order.edges = edges
    return order


# ===== API models =====
class OrderRequest(BaseModel):
    manufacturer: str = Field(default=MANUFACTURER)
    serial_number: str = Field(default=SERIAL_NUMBER)
    order_id: str = Field(default="example_master_route")


class OrderSummary(BaseModel):
    order_id: str
    nodes: int
    edges: int
    first_node_id: str
    sequence: str


class AssignResponse(BaseModel):
    endpoint: str
    assigned: bool
    decision: str
    errors: list[str]
    order: OrderSummary


# ===== Master lifecycle =====
class _State:
    master: vda.VDA5050Master | None = None


state = _State()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Best-effort: the server still starts (and Swagger is demoable) even with
    # no broker — connect()/onboard just log failures.
    try:
        mqtt = vda.create_default_mqtt_client(BROKER, CLIENT_ID)
        master = vda.VDA5050Master.make(mqtt)
        master.connect()
        master.onboard_agv(MANUFACTURER, SERIAL_NUMBER)
        ok, errs = master.load_map_from_config(str(Path(__file__).parent / "large_artc_map.json"))
        if not ok:
            stderr_console.print("Map load FAILED:")
            pprint(errs, console=stderr_console)
        state.master = master
        print(f"Master connected={master.is_connected()}, onboarded "
              f"{MANUFACTURER}/{SERIAL_NUMBER}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 — keep the webserver up regardless
        print(f"Master startup failed (server still up): {exc}", file=sys.stderr)
    yield
    if state.master is not None:
        try:
            state.master.disconnect()
        except Exception as exc:  # noqa: BLE001
            print(f"Master disconnect failed: {exc}", file=sys.stderr)


TAGS = [
    {"name": "1 · Orders", "description": "Assign the demo route."},
    {"name": "2 · Status", "description": "Master / AGV observability."},
]

app = FastAPI(
    title="VDA5050 Example Master Webserver",
    description=__doc__,
    version="0.1.0",
    openapi_tags=TAGS,
    lifespan=lifespan,
)


def _require_master() -> vda.VDA5050Master:
    if state.master is None:
        raise HTTPException(503, "Master not initialized (startup failed).")
    return state.master


def _assign(endpoint: str, req: OrderRequest, order: vda.Order):
    master = _require_master()
    result = master.assign_order(req.manufacturer, req.serial_number, order)
    return AssignResponse(
        endpoint=endpoint,
        assigned=bool(result),
        decision=result.decision.name,
        errors=[e.error_type for e in result.errors],
        order=OrderSummary(
            order_id=order.order_id,
            nodes=len(order.nodes),
            edges=len(order.edges),
            first_node_id=order.nodes[0].node_id if order.nodes else "",
            sequence=route_diagram(),
        ),
    )


# ===== Order endpoint =====
@app.post(
    "/orders/route",
    response_model=AssignResponse,
    tags=["1 · Orders"],
    summary="Assign the demo route as a VDA5050 Order",
    description=(
        "Assign the hardcoded demo route as a VDA5050 `Order` and deliver it "
        "over MQTT. The route is a chain of map nodes joined by edges:\n\n"
        "```\n"
        f"{route_diagram()}\n"
        "```\n\n"
        "Nodes carry interleaved sequence ids (0,2,4,6) and edges sit between "
        "them (1,3,5); all are released. The robot navigates freely between "
        "nodes (no trajectory sent, §6.1.1).\n\n"
        "Returns the assignment decision plus a summary of the order. With no "
        "live, ready AGV the master's readiness pre-flight yields "
        "`AGV_OFFLINE` / `AGV_NO_STATE_YET` rather than publishing."
    ),
)
def order_route(req: OrderRequest = OrderRequest()):
    order = build_route_order(req.order_id)
    return _assign("route", req, order)


# ===== Status =====
@app.get("/status", tags=["2 · Status"], summary="Master and AGV state")
def status():
    master = _require_master()
    agvs = []
    for mfg, serial in master.get_onboarded_agvs():
        agv = master.get_agv(mfg, serial)
        last = agv.get_last_state() if agv else None
        pose = last.agv_position if last is not None else None
        agvs.append({
            "manufacturer": mfg,
            "serial_number": serial,
            "connection_status": agv.get_connection_status().name if agv else None,
            "operational_state": agv.get_operational_state().name if agv else None,
            "last_node_id": last.last_node_id if last is not None else None,
            "has_pose": bool(pose is not None and pose.position_initialized),
        })
    return {"broker_connected": master.is_connected(), "agvs": agvs}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
