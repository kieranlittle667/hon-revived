"""Regression coverage for independent REST recovery and unload cleanup."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntries
from custom_components.hon import async_setup_entry, async_unload_entry
from custom_components.hon.const import DOMAIN
from custom_components.hon.recovery import HonStateRecovery


def device(name, error=None):
    return SimpleNamespace(unique_id=name, update=AsyncMock(side_effect=error))


@pytest.mark.asyncio
async def test_failed_appliance_does_not_prevent_other_refresh_or_recovery():
    dryer, washer = device("dryer", OSError()), device("washer")
    recovery = HonStateRecovery(SimpleNamespace(appliances=[dryer, washer]))
    assert await recovery.refresh() == {"dryer": False, "washer": True}
    washer.update.assert_awaited_once_with(force=True)
    dryer.update.side_effect = None
    assert await recovery.refresh() == {"dryer": True, "washer": True}


@pytest.mark.asyncio
async def test_timeout_and_close_do_not_leave_refresh_tasks():
    async def stalled(**kwargs):
        await asyncio.sleep(100)

    dryer, washer = device("dryer", stalled), device("washer")
    recovery = HonStateRecovery(
        SimpleNamespace(appliances=[dryer, washer]), timeout=0.01
    )
    assert await recovery.refresh() == {"dryer": False, "washer": True}
    recovery.timeout = 100
    task = asyncio.create_task(recovery.refresh())
    await asyncio.sleep(0)
    await recovery.close()
    assert task.cancelled()
    before = dryer.update.await_count
    await recovery.refresh()
    assert dryer.update.await_count == before


@pytest.mark.asyncio
async def test_pushes_do_not_postpone_poll_and_unload_closes_client(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    entry = SimpleNamespace(
        unique_id="account",
        data={"email": "test@example.invalid", "password": "fake"},
        async_on_unload=Mock(),
    )
    hon = SimpleNamespace(
        appliances=[device("dryer"), device("washer")],
        api=SimpleNamespace(auth=SimpleNamespace(refresh_token="fake")),
        subscribe_updates=Mock(),
        close=AsyncMock(),
    )
    factory = Mock(return_value=SimpleNamespace(create=AsyncMock(return_value=hon)))
    cancel_timer = Mock()
    try:
        with patch("custom_components.hon.Hon", factory), patch(
            "custom_components.hon.aiohttp_client.async_get_clientsession",
            return_value=Mock(),
        ), patch(
            "custom_components.hon.async_track_time_interval", return_value=cancel_timer
        ) as timer, patch.object(
            hass.config_entries, "async_update_entry"
        ), patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ), patch.object(
            hass.config_entries,
            "async_unload_platforms",
            new=AsyncMock(return_value=True),
        ):
            assert await async_setup_entry(hass, entry)
            tick = timer.call_args.args[1]
            assert timer.call_args.args[2].total_seconds() == 300
            push = hon.subscribe_updates.call_args.args[0]
            for _ in range(50):
                push(None)
            await asyncio.sleep(0)
            timer.assert_called_once()
            await tick(None)
            for appliance in hon.appliances:
                appliance.update.assert_awaited_once_with(force=True)
            assert await async_unload_entry(hass, entry)
            cancel_timer.assert_called_once()
            hon.close.assert_awaited_once()
            hon.subscribe_updates.assert_called_with(None)
            assert DOMAIN not in hass.data
    finally:
        await hass.async_stop()
