# Copyright 2026 ROS-Industrial Consortium Asia Pacific
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import vda5050._core as core

import vda5050 as vda


def test_version():
    assert vda.__version__ == "0.0.1"


def test_no_master_submodule():
    assert not hasattr(core, "master")
    assert not hasattr(vda, "VDA5050Master")


def test_client_state_manager_has_initialize_position():
    assert hasattr(core.client.StateManager, "initialize_position")


def test_rmf_migration_imports():
    assert vda.Adapter is not None
    assert vda.FleetConfiguration is not None
    assert vda.RobotConfiguration is not None


def test_rmf_smoke_constructs_without_broker():
    state = vda.RobotState("demo-map", (1.0, 2.0, 0.0), 0.8)
    config = vda.RobotConfiguration("ACME", "AGV-001")
    fleet = vda.FleetConfiguration(
        "demo-fleet", "tcp://localhost:1883", "demo-client"
    )
    adapter = vda.Adapter.make()

    assert state.map == "demo-map"
    assert config.manufacturer == "ACME"
    assert fleet.fleet_name == "demo-fleet"
    assert adapter is not None
