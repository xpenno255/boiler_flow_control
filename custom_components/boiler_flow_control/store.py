"""JSON persistence for Boiler Flow Control state (last write, demand filter, etc.)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


class BFCStore:
    """Persistent JSON storage for hub state.

    Data is persisted to .storage/boiler_flow_control_{entry_id} as JSON.
    """

    def __init__(self, hass: Any, entry_id: str) -> None:
        self._hass = hass
        self._path = Path(hass.config.path(f".storage/boiler_flow_control_{entry_id}"))
        self._data: dict[str, Any] = {}

    async def async_load(self) -> dict[str, Any]:
        try:
            data = await self._hass.async_add_executor_job(self._read_file)
            self._data = data if isinstance(data, dict) else {}
        except FileNotFoundError:
            self._data = {}
        except (json.JSONDecodeError, OSError) as err:
            _LOGGER.warning("Failed to load BFC store %s: %s", self._path, err)
            self._data = {}
        return self._data

    async def async_save(self) -> None:
        try:
            await self._hass.async_add_executor_job(self._write_file)
        except OSError as err:
            _LOGGER.error("Failed to save BFC store %s: %s", self._path, err)

    def _read_file(self) -> Any:
        with open(self._path, encoding="utf-8") as fh:
            return json.load(fh)

    def _write_file(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)
        tmp.replace(self._path)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
