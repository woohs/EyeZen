from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _quote_argument(value: str) -> str:
    return f'"{value}"'


def build_startup_command(executable_path: str, launch_target: Path | None) -> str:
    parts = [_quote_argument(str(executable_path))]
    if launch_target is not None:
        parts.append(_quote_argument(str(launch_target)))
    parts.append("--minimized")
    return " ".join(parts)


def _load_registry_module() -> Any | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    return winreg


class StartupManager:
    def __init__(self, app_name: str = "EyeZen", registry: Any | None = None):
        self.app_name = app_name
        self.registry = registry if registry is not None else _load_registry_module()

    def is_supported(self) -> bool:
        return self.registry is not None

    def is_enabled(self) -> bool:
        value = self.get_command()
        return bool(value)

    def get_command(self) -> str | None:
        if not self.is_supported():
            return None
        key = None
        try:
            key = self.registry.OpenKey(
                self.registry.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                self.registry.KEY_READ,
            )
            value, _ = self.registry.QueryValueEx(key, self.app_name)
            return str(value)
        except (FileNotFoundError, KeyError):
            return None
        except OSError:
            return None
        finally:
            if key is not None:
                self.registry.CloseKey(key)

    def set_enabled(self, command: str, enabled: bool) -> bool:
        if not self.is_supported():
            return False
        key = None
        try:
            key = self.registry.OpenKey(
                self.registry.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                self.registry.KEY_SET_VALUE,
            )
            if enabled:
                self.registry.SetValueEx(key, self.app_name, 0, self.registry.REG_SZ, command)
            else:
                try:
                    self.registry.DeleteValue(key, self.app_name)
                except FileNotFoundError:
                    pass
            return True
        except OSError:
            return False
        finally:
            if key is not None:
                self.registry.CloseKey(key)