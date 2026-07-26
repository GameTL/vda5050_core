# Python package for vda5050_core

Installable bindings for the C++ `vda5050_core` library. The distribution name
and import name are both `vda5050`.

## Install from source

```bash
# Prerequisites: CMake, Ninja, Python 3.12, Paho MQTT C++, fmt, nlohmann-json
bash vda5050_core/python/scripts/install-native-deps.sh   # from repo root

cd vda5050_core/python
# On macOS, prefer Apple Clang if Homebrew LLVM is on PATH:
#   export CC=/usr/bin/clang CXX=/usr/bin/clang++
pip install --verbose . --group test
pytest
```

## Install a released wheel

Download the matching `.whl` from the GitHub Release assets for a `v*.*.*`
tag, then:

```bash
pip install path/to/vda5050-0.0.1-*.whl
```

## Examples

See `examples/mqtt_pair/` for a robot adapter over MQTT. Pair it with an
external/C++ master if needed — this package does not expose a Python master.

## Releasing

1. Bump `version` in this `pyproject.toml` and `vda5050_core/package.xml`.
2. Merge to `main`.
3. Push an annotated tag:

```bash
git tag -a v0.0.1 -m "Release v0.0.1"
git push origin v0.0.1
```

The `Wheels` workflow builds wheels and attaches them to a GitHub Release.
Merging to `main` alone does not publish a release.
