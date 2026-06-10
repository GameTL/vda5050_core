# To Run the autoxing client Python Bindings -> Spellbook

Requires spellbook venv (`cd ~/autoxing_spellbook/autoxing-spellbook-cli && uv sync`).
Bridge code lives in `autoxing_bridge/`; this folder keeps only the VDA5050 client entrypoint.

**Multi-node routes:** `on_navigate` returns immediately and drives the robot on a worker thread.

```bash
source install/setup.bash
cd vda5050_core_py/autoxing-l300
python3 example_autoxing_client.py
```

**Terminal 2 — publish demo order and verify state:**

```bash
python3 publish_autoxing_l300_route.py --wait-route
```

**Terminal 3 (alternative to Terminal 2) — master webserver (FastAPI + Swagger):**

Drives the bound `VDA5050Master` instead of publishing raw MQTT. Two priority
endpoints: `/orders/with-state-prepend` (spec-compliant, reads the AGV pose) and
`/orders/misaligned-no-prepend` (intentionally violates §6.6.1).

Runs with [uv](https://docs.astral.sh/uv/) — fastapi/uvicorn are declared in the
script's PEP 723 inline metadata, so uv provisions an isolated env on first run.
Source the workspace first so the colcon-built `vda5050_core_py` is on
`PYTHONPATH` (uv inherits it; `--python 3.10` matches the binding's ABI):

```bash
source ../../install/setup.bash      # exports vda5050_core_py on PYTHONPATH
uv run --python 3.10 example_master_webserver.py
# open http://127.0.0.1:8000/docs
```

Optional spellbook-only test CLIs (run from `autoxing-l300/`):

```bash
python3 -m autoxing_bridge.navigate_node -11.0 1.2 0.0
python3 -m autoxing_bridge.poll_robot
python3 -m autoxing_bridge.wait_for_move -11.0 1.2 0.0
```
