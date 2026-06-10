# TODO

Tracking items from the master/adapter design discussion (2026-06-02).
Workflow target: `Browser → master (Python/FastAPI) → order → protocol_adapter
→ MQTT → client_adapter (Python binding) → AutoXing L300 robot`.

## Spec-compliance items

- [x] **AutoXing is a *freely-navigating* vehicle (VDA5050 §3, §6.1.1).**
  It plans its own path between nodes, so the master MUST omit the `trajectory`
  edge attribute and send node positions only. The robot does local nav /
  obstacle avoidance itself (`autoxing_bridge/bridge.py` → `navigate(x,y,theta)`).
  Demo guard added: `publish_autoxing_l300_route.py` edges block documents the
  trajectory-free intent (Step 2). **Still open for the master:** when the
  C++/Python master lands, enforce that it never emits `trajectory` for this AGV
  and confirm the factsheet advertises self-planning so we don't send optional
  fields it cannot use (§6.1.1).

- [ ] **First node must be trivially reachable (§6.6.1, §6.6.3.1).**
  The demo's first node `node_table` (-11.0, 1.2) has no `allowedDeviationXY`
  (defaults to 0.0 = no deviation), so a spec-strict AGV would reject it unless
  the robot is physically on that point. Fix: before publishing, read the
  robot's current pose (state topic `agvPosition` / AutoXing `/tracked_pose`)
  and **prepend a temporary node at the current pose** as `sequenceId 0`, then
  renumber (§6.6.3.1 option 1). Today there is no master in the loop, so
  `publish_autoxing_l300_route.py` would need to do the get-state-then-prepend;
  once the master exists, this becomes the master's responsibility.

## Architecture items

- [x] **Master Python binding (keystone).** Done (Step 3) —
  `vda5050_core_py/src/master_bindings.{hpp,cpp}` bind `VDA5050Master`
  (`make`, `connect`/`disconnect`, `onboard`/`offboard`/`is_onboarded`/
  `get_onboarded_agvs`, `assign_order`, `publish_order`, `get_agv`) with a
  `PyVDA5050Master` trampoline for the `on_*` callbacks, plus the order/state
  types (`Order`, `Edge`, `Header`, `State`, `NodeState`, `EdgeState`,
  `Error`, `AssignmentResult`) and enums (`ConnectionState`, `OperatingMode`,
  `ErrorLevel`, `AGVState`, `AssignmentDecision`). `test/test_master_smoke.py`
  covers it. **Still open:** `on_connection`/`on_factsheet`/`on_visualization`/
  `on_loads_changed`/`on_broker_*` callbacks (need their message types bound)
  and `load_map_from_config` / `set_map` (need `Map`/`MapLoadResult` bound).

- [ ] **Route calculation is upstream, not in this library.** VDA5050 §5 lists
  "route calculation and guidance" as a master-control function, but
  `vda5050_core` does NOT implement a planner — `master/map/map.hpp` is a static
  topology for *validation* only (no graph search). The node/edge graph comes
  from **RMF2 MAPF Plan Executor + Plan server** upstream of the master. The
  master only validates / stitches / delivers / tracks.

- [ ] **AGV readiness lifecycle.** `assign_order` rejects unless the AGV is
  ONLINE + AUTOMATIC + position-initialized. The AutoXing adapter must publish a
  conformant State or the master refuses orders the raw demo script would send.

- [ ] **Coordinate / mapId contract (§6.7).** AutoXing meters + `mapId:"LargeARTC"`
  must agree with the loaded topology Map or traversability validation trips.

- [ ] **FastAPI ↔ MQTT threading.** Master callbacks fire on the MQTT thread;
  bridge cleanly into FastAPI's async loop (queue / event-loop hand-off).
