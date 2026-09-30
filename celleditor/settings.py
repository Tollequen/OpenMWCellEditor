"""The editor's per-user settings: recent projects, the game's files and the access code."""
import json
import os
import secrets
import sys

CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def config_dir():
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "OpenMWCellEditor")
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming"), "OpenMWCellEditor")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "openmw-cell-editor")


def projects_dir():
    """Where the editor keeps its projects' edits, history and reference numbers."""
    return os.environ.get("CELLEDITOR_PROJECTS") or os.path.join(config_dir(), "projects")


def new_code(exclude=None):
    """A new six-character access code without look-alike characters."""
    while True:
        code = "".join(secrets.choice(CODE_LETTERS) for _ in range(6))
        if code != exclude:
            return code


class Settings:
    def __init__(self, path=None):
        self.path = path or self.default_path()
        self.data = {}
        try:
            with open(self.path) as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            pass

    @staticmethod
    def default_path():
        return os.environ.get("CELLEDITOR_SETTINGS") or os.path.join(config_dir(), "settings.json")

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def recent(self):
        """Recent project files that still exist, newest first."""
        return [p for p in self.data.get("recent", []) if os.path.exists(p)]

    def add_recent(self, path):
        path = os.path.abspath(path)
        self.set("recent", [path] + [p for p in self.data.get("recent", []) if p != path][:9])

    def lan_code(self, new=False):
        """The access code for other devices, made once and kept unless new is set."""
        code = self.data.get("lan_code")
        if not code or new:
            code = new_code(exclude=code)
            self.set("lan_code", code)
        return code
