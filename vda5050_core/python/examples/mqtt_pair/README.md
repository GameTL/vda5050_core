# MQTT Robot Adapter Example

This script runs one VDA5050 robot adapter against an anonymous MQTT broker.
Pair it with an external/C++ master if you need fleet-side control — this
Python package does not expose a master API.

## Prerequisites

Install the package from the packaging root:

```bash
cd vda5050_core/python
pip install --verbose .
```

The current Python transport surface does not expose MQTT username, password,
or TLS configuration, so this example expects an anonymous local broker.

## Run

Start MQTT broker:

```bash
# Terminal 1
mosquitto -v
```

Start the robot adapter:

```bash
# Terminal 2
python examples/mqtt_pair/robot_adapter.py
```

The adapter uses this identity and topic prefix:

```text
manufacturer: ACME
serial number: AGV-001
topics: uagv/v2/ACME/AGV-001/...
```

The internal client adapter publishes its periodic state every 30 seconds, so
the first state message may take up to 30 seconds to appear. Stop with
`Ctrl+C`.

Override broker and identity with:

```bash
export MQTT_BROKER=tcp://localhost:1883
export VDA5050_MANUFACTURER=ACME
export VDA5050_SERIAL_NUMBER=AGV-001
export ROBOT_MQTT_CLIENT_ID=example-robot-adapter-acme-agv-001
```
