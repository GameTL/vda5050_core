# VDA5050 Library and Support Tools

`vda5050_core` is a modern C++ library for developing applications that
communicate using the VDA5050 specification. It provides reusable components
for both AGV-side and master-control implementations, including message types
in C++ along with serialization and deserialization utilities, validation,
execution utilities, MQTT communication and a high-level adapter API for
robot integration.

The library is framework independent and can be integrated into standalone
C++ applications, ROS 2 systems or existing robot software.

## Python package (`vda5050`)

Python bindings live under [`vda5050_core/python`](vda5050_core/python) and
install as the `vda5050` package (pip / wheel).

```bash
# Native deps (Paho MQTT C++, fmt, nlohmann-json)
bash .github/scripts/install-native-deps.sh

cd vda5050_core/python
pip install --verbose . --group test
pytest
```

Tag pushes matching `v*.*.*` build wheels and attach them to a GitHub Release
(see `.github/workflows/wheels.yml`). See
[`vda5050_core/python/README.md`](vda5050_core/python/README.md) for details.

## Features
