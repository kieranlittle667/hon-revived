"""Adapt HA's POSIX-only integration-frame lookup for local Windows tests."""

import inspect
import os

import pytest

from homeassistant.helpers import frame


@pytest.fixture(autouse=True)
def windows_integration_frame_paths(monkeypatch):
    """Recognize custom integration frames as HA does on its Linux host."""
    if os.name != "nt":
        return
    original = frame.get_integration_frame

    def normalized_frame(exclude_integrations=None):
        try:
            return original(exclude_integrations)
        except frame.MissingIntegrationFrame:
            current = inspect.currentframe()
            while current:
                filename = current.f_code.co_filename.replace("\\", "/")
                marker = "custom_components/"
                if marker in filename:
                    relative = filename.split(marker, 1)[1]
                    domain = relative.split("/", 1)[0]
                    if domain not in (exclude_integrations or set()):
                        return frame.IntegrationFrame(
                            custom_integration=True,
                            integration=domain,
                            module=None,
                            relative_filename=relative,
                            frame=current,
                        )
                current = current.f_back
            raise

    monkeypatch.setattr(frame, "get_integration_frame", normalized_frame)
