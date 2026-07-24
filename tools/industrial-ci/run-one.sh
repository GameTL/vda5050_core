#!/usr/bin/env bash
# Run one industrial_ci matrix cell locally, matching .github/workflows/build.yml.
set -euo pipefail

DISTRO="${1:?usage: $0 <humble|jazzy> <gcc|clang|gcc-asan|gcc-tsan>}"
TEST_TYPE="${2:?usage: $0 <humble|jazzy> <gcc|clang|gcc-asan|gcc-tsan>}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ICI_REF="${ICI_REF:-master}"

case "$DISTRO" in
  humble | jazzy) ;;
  *)
    echo "unknown distro: $DISTRO" >&2
    exit 2
    ;;
esac

TARGET_CMAKE_ARGS='-DENABLE_ROS2=ON'
ADDITIONAL_DEBS=""
CC=""
CXX=""

case "$TEST_TYPE" in
  gcc) ;;
  clang)
    ADDITIONAL_DEBS="clang lld"
    CC="clang"
    CXX="clang++"
    ;;
  gcc-asan)
    TARGET_CMAKE_ARGS='-DENABLE_ROS2=ON -DCMAKE_C_FLAGS="-fsanitize=address -O1 -g -fno-omit-frame-pointer" -DCMAKE_CXX_FLAGS="-fsanitize=address -O1 -g -fno-omit-frame-pointer"'
    ;;
  gcc-tsan)
    TARGET_CMAKE_ARGS='-DENABLE_ROS2=ON -DCMAKE_C_FLAGS="-fsanitize=thread -O2 -g -fno-omit-frame-pointer" -DCMAKE_CXX_FLAGS="-fsanitize=thread -O2 -g -fno-omit-frame-pointer"'
    ;;
  *)
    echo "unknown test_type: $TEST_TYPE" >&2
    exit 2
    ;;
esac

if [[ "$DISTRO" != jazzy && "$TEST_TYPE" == gcc-* ]]; then
  echo "$TEST_TYPE only exists in the jazzy CI matrix" >&2
  exit 2
fi

echo "=== industrial_ci: distro=$DISTRO test_type=$TEST_TYPE ==="

docker run --rm \
  --platform linux/amd64 \
  -v "$REPO_ROOT:/github/workspace:rw" \
  -w /github/workspace \
  -e CI=true \
  -e ISOLATION=shell \
  -e ROS_DISTRO="$DISTRO" \
  -e UPSTREAM_WORKSPACE='github:ros-industrial/vda5050_interfaces#main github:eclipse-paho/paho.mqtt.cpp#v1.5.0' \
  -e TARGET_CMAKE_ARGS="$TARGET_CMAKE_ARGS" \
  -e ADDITIONAL_DEBS="$ADDITIONAL_DEBS" \
  -e CC="$CC" \
  -e CXX="$CXX" \
  -e GITHUB_WORKSPACE=/github/workspace \
  -e GITHUB_REPOSITORY="local/vda5050_core_gametl" \
  -e GITHUB_OUTPUT=/tmp/github_output \
  "ros:${DISTRO}-ros-core" \
  bash -lc "
    set -euo pipefail
    : > /tmp/github_output
    apt-get update -qq -y
    apt-get install -y -qq libpaho-mqtt-dev libpaho-mqttpp-dev mosquitto git ca-certificates
    mosquitto -d
    sleep 2
    rm -rf /tmp/industrial_ci
    git clone --quiet --depth 1 https://github.com/ros-industrial/industrial_ci.git /tmp/industrial_ci -b ${ICI_REF}
    bash /tmp/industrial_ci/.github/action.sh
  "

echo "=== passed: distro=$DISTRO test_type=$TEST_TYPE ==="
