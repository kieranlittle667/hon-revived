"""Exercise platform loading and laundry state on the target HA runtime."""

import asyncio
import importlib
import json
import logging
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock

import pytest

from homeassistant import loader
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntries
from homeassistant.helpers import frame
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pyhon.appliance import HonAppliance
from pyhon.attributes import HonAttribute
from pyhon.connection.mqtt import MQTTClient

from custom_components.hon.const import DOMAIN, PLATFORMS
from custom_components.hon.recovery import HonStateRecovery


@pytest.mark.asyncio
async def test_platform_imports_on_target_home_assistant(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    component = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN
    manifest = json.loads((component / "manifest.json").read_text(encoding="utf-8"))
    integration = loader.Integration(hass, "custom_components.hon", component, manifest)
    hass.data[loader.DATA_CUSTOM_COMPONENTS] = {DOMAIN: integration}
    hass.data[loader.DATA_INTEGRATIONS][DOMAIN] = integration
    try:
        for platform in PLATFORMS:
            module = importlib.import_module(f"custom_components.hon.{platform}")
            assert callable(module.async_setup_entry)
    finally:
        await hass.async_stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["WM", "TD"])
async def test_laundry_entities_follow_completion_and_disconnect(tmp_path, kind):
    from custom_components.hon.binary_sensor import (
        BINARY_SENSORS,
        HonBinarySensorEntity,
    )
    from custom_components.hon.sensor import SENSORS, HonSensorEntity
    from custom_components.hon.switch import SWITCHES, HonControlSwitchEntity

    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    frame.async_setup(hass)
    try:
        device = await HonAppliance(
            None,
            {
                "applianceTypeName": kind,
                "macAddress": "00-11-22-33-44-55",
                "topics": {
                    "subscribe": ["fixture/appliancestatus", "fixture/disconnected"]
                },
            },
        ).create()
        device.attributes["parameters"] = {
            "machMode": HonAttribute("2"),
            "prCode": HonAttribute("0"),
            "doorStatus": HonAttribute("1"),
            "remoteCtrValid": HonAttribute("1"),
        }
        device.attributes["activity"] = {"cycle": "running snapshot"}
        device.connection = True
        device.refresh_derived_attributes()
        hon = SimpleNamespace(api=Mock(), appliances=[device], notify=Mock())
        recovery = HonStateRecovery(hon)
        coordinator = DataUpdateCoordinator(
            hass, logging.getLogger(__name__), name="test", config_entry=None
        )
        coordinator.async_set_updated_data({})
        hass.data[DOMAIN] = {
            "fixture": {"hon": hon, "recovery": recovery, "coordinator": coordinator}
        }
        entry = SimpleNamespace(unique_id="fixture")
        active = HonControlSwitchEntity(
            hass, entry, device, next(d for d in SWITCHES[kind] if d.key == "active")
        )
        status = HonSensorEntity(
            hass, entry, device, next(d for d in SENSORS[kind] if d.key == "machMode")
        )
        assert active.is_on is True
        assert active.available is True
        assert active.unique_id == "00-11-22-33-44-55active"
        assert status.unique_id == "00-11-22-33-44-55machMode"
        mqtt = MQTTClient(hon, "offline-fixture")
        mqtt._loop = asyncio.get_running_loop()

        async def deliver(topic, payload):
            mqtt._on_publish_received(
                SimpleNamespace(
                    publish_packet=SimpleNamespace(
                        topic=topic, payload=json.dumps(payload).encode()
                    )
                )
            )
            await asyncio.sleep(0)

        await deliver(
            "fixture/appliancestatus",
            {"parameters": [{"parName": "machMode", "parNewVal": "1"}]},
        )
        status._handle_coordinator_update(update=False)
        assert active.is_on is False
        assert status.native_value == "ready"
        recovery.available[device.unique_id] = False
        assert active.available is False
        assert status.available is False
        recovery.available[device.unique_id] = True
        assert active.available is True
        await deliver("fixture/disconnected", {})
        assert active.available is False
        if kind == "TD":
            connection = HonBinarySensorEntity(
                hass,
                entry,
                device,
                next(
                    d
                    for d in BINARY_SENSORS[kind]
                    if d.key == "attributes.lastConnEvent.category"
                ),
            )
            assert connection.is_on is False
        await recovery.close()
        await mqtt.close()
    finally:
        await hass.async_stop()
