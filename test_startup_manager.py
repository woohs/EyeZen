import unittest
from pathlib import Path

from startup_manager import (
    RUN_KEY_PATH,
    StartupManager,
    build_startup_command,
)


class RegistryStub:
    HKEY_CURRENT_USER = object()
    KEY_READ = 0x0001
    KEY_SET_VALUE = 0x0002
    REG_SZ = 1

    def __init__(self):
        self.values = {}

    def OpenKey(self, hive, path, reserved=0, access=0):
        return (hive, path)

    def SetValueEx(self, key, name, reserved, kind, value):
        _, path = key
        self.values[(path, name)] = (kind, value)

    def DeleteValue(self, key, name):
        _, path = key
        marker = (path, name)
        if marker not in self.values:
            raise FileNotFoundError(name)
        del self.values[marker]

    def QueryValueEx(self, key, name):
        _, path = key
        kind, value = self.values[(path, name)]
        return value, kind

    def CloseKey(self, key):
        return None


class StartupManagerTests(unittest.TestCase):
    def test_build_startup_command_for_script_mode(self):
        command = build_startup_command(
            executable_path=r"C:\Python312\python.exe",
            launch_target=Path(r"D:\project\other\EyeZen\main.py"),
        )

        self.assertEqual(
            command,
            '"C:\\Python312\\python.exe" "D:\\project\\other\\EyeZen\\main.py" --minimized',
        )

    def test_build_startup_command_for_frozen_mode(self):
        command = build_startup_command(
            executable_path=r"D:\Apps\EyeZen.exe",
            launch_target=None,
        )

        self.assertEqual(command, '"D:\\Apps\\EyeZen.exe" --minimized')

    def test_startup_manager_can_enable_and_disable_registry_value(self):
        registry = RegistryStub()
        manager = StartupManager(app_name="EyeZen", registry=registry)

        manager.set_enabled('"D:\\Apps\\EyeZen.exe" --minimized', True)
        self.assertTrue(manager.is_enabled())
        self.assertEqual(
            registry.values[(RUN_KEY_PATH, "EyeZen")][1],
            '"D:\\Apps\\EyeZen.exe" --minimized',
        )

        manager.set_enabled('"D:\\Apps\\EyeZen.exe" --minimized', False)
        self.assertFalse(manager.is_enabled())