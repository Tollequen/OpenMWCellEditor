"""The game's data folders, archives and content files, found the way OpenMW finds them."""
import os
import sys

from .bsa import Archive


def cfg_candidates():
    """The openmw.cfg files that exist where OpenMW keeps them on this system."""
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        paths = [os.path.join(home, "Library", "Preferences", "openmw", "openmw.cfg")]
    elif sys.platform == "win32":
        docs = [os.path.join(home, "Documents")]
        if os.environ.get("OneDrive"):
            docs.append(os.path.join(os.environ["OneDrive"], "Documents"))
        paths = [os.path.join(d, "My Games", "OpenMW", "openmw.cfg") for d in docs]
    else:
        paths = [os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "openmw", "openmw.cfg"),
                 os.path.join(home, ".var", "app", "org.openmw.OpenMW", "config", "openmw", "openmw.cfg")]
    return [p for p in paths if os.path.exists(p)]


def openmw_cfg():
    """The openmw.cfg in use, or None."""
    found = cfg_candidates()
    return found[0] if found else None


def _quoted(v):
    return '"%s"' % v.replace("&", "&&").replace('"', '&"')


def add_to_cfg(path, folder, plugin):
    """Add a data folder and a plugin to an openmw.cfg unless it has them, keeping a backup."""
    cfg = read_cfg(path)
    have_dir = any(os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(path), d))) ==
                   os.path.normcase(os.path.abspath(folder)) for d in cfg.get("data", []))
    have_plugin = any(c.lower() == plugin.lower() for c in cfg.get("content", []))
    if have_dir and have_plugin:
        return False
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    with open(path + ".celleditor-backup", "w", encoding="utf-8") as f:
        f.write(text)
    lines = text.splitlines()
    if not have_dir:
        # After the last data= line (the highest priority), or at the end
        at = max([i for i, l in enumerate(lines) if l.strip().startswith("data=")] or [len(lines) - 1]) + 1
        lines.insert(at, "data=" + _quoted(folder))
    if not have_plugin:
        lines.append("content=" + plugin)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    return True


def _value(v):
    """An openmw.cfg value: "quoted" with & escaping, or plain."""
    v = v.strip()
    if not v.startswith('"'):
        return v
    out, i = [], 1
    while i < len(v):
        c = v[i]
        if c == "&" and i + 1 < len(v):
            out.append(v[i + 1])
            i += 2
            continue
        if c == '"':
            break
        out.append(c)
        i += 1
    return "".join(out)


def read_cfg(path):
    """{key: [values]} of an openmw.cfg, in file order."""
    out = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out.setdefault(k.strip(), []).append(_value(v))
    return out


LOOSE_FOLDERS = ("meshes", "textures")
DEFAULT_CONTENT = ("Morrowind.esm", "Tribunal.esm", "Bloodmoon.esm")


class GameData:
    """The data folders, archives and content files of a game, later ones winning."""

    def __init__(self, data_dirs, archives=("Morrowind.bsa", "Tribunal.bsa", "Bloodmoon.bsa"), content=None):
        self.data_dirs = [d for d in data_dirs if os.path.isdir(d)]
        self._archives = None
        self._loose = None
        self.archive_names = list(archives)
        self.all_content = list(content) if content is not None else self._plugins_in_folders()
        self.content = list(content) if content is not None else [c for c in DEFAULT_CONTENT if self.find(c)]
        self.cfg_path = None
        self.wanted_dirs = list(data_dirs)

    def _plugins_in_folders(self):
        """The TES3 files in the data folders in Morrowind's order: masters first, then by date."""
        found = {}
        for d in self.data_dirs:
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for f in names:
                if f.lower().endswith((".esm", ".esp", ".omwaddon")):
                    found[f.lower()] = os.path.join(d, f)
        official = [n for n in DEFAULT_CONTENT if n.lower() in found]
        rest = sorted((p for k, p in found.items() if k not in {n.lower() for n in official}),
                      key=lambda p: (not p.lower().endswith(".esm"), os.path.getmtime(p)))
        return official + [os.path.basename(p) for p in rest]

    def choose(self, names=None):
        """Show only these content files and the masters they need; Morrowind.esm always."""
        from .loadorder import TES3_EXTENSIONS, masters_of
        tes3 = [c for c in self.all_content if c.lower().endswith(TES3_EXTENSIONS)]
        want = {n.lower() for n in (names if names is not None else DEFAULT_CONTENT)} | {"morrowind.esm"}
        todo = list(want)
        while todo:
            path = self.find(todo.pop())
            for m in (masters_of(path) if path else []):
                if m.lower() not in want:
                    want.add(m.lower())
                    todo.append(m.lower())
        self.content = [c for c in tes3 if c.lower() in want]
        return self.content

    @classmethod
    def from_cfg(cls, path=None):
        path = path or openmw_cfg()
        if not path:
            raise FileNotFoundError("openmw.cfg not found; start the editor with --data \"<Data Files folder>\"")
        cfg = read_cfg(path)
        base = os.path.dirname(path)
        dirs = [d if os.path.isabs(d) else os.path.join(base, d) for d in cfg.get("data", [])]
        game = cls(dirs, cfg.get("fallback-archive", ["Morrowind.bsa"]), cfg.get("content", []))
        game.cfg_path = os.path.abspath(path)
        game.wanted_dirs = dirs
        return game

    def find(self, name):
        """A file in the data folders by name, any case, the last folder winning."""
        low = name.lower()
        for d in reversed(self.data_dirs):
            try:
                for f in os.listdir(d):
                    if f.lower() == low:
                        return os.path.join(d, f)
            except OSError:
                continue
        return None

    def master(self, name):
        path = self.find(name)
        if not path:
            raise FileNotFoundError("%s is not in any data folder: %s" % (name, self.data_dirs))
        return path

    @property
    def archives(self):
        """The archives, highest priority first."""
        if self._archives is None:
            found = [self.find(a) for a in self.archive_names]
            self._archives = [Archive(p) for p in reversed(found) if p]
        return self._archives

    def loose(self):
        """{relative path: file} of the loose meshes and textures in the data folders, later ones winning."""
        if self._loose is None:
            out = {}
            for d in self.data_dirs:
                try:
                    tops = [t for t in os.listdir(d) if t.lower() in LOOSE_FOLDERS]
                except OSError:
                    continue
                for top in tops:
                    for root, _, files in os.walk(os.path.join(d, top)):
                        rel = os.path.relpath(root, d).replace(os.sep, "\\").lower()
                        for f in files:
                            out[rel + "\\" + f.lower()] = os.path.join(root, f)
            self._loose = out
        return self._loose

    def read(self, name):
        """Bytes of a game file, e.g. 'meshes\\x\\y.nif', or None."""
        key = name.lower().replace("/", "\\")
        path = self.loose().get(key)
        if path:
            with open(path, "rb") as f:
                return f.read()
        for a in self.archives:
            if a.has(key):
                return a.read(key)
        return None

    def has(self, name):
        key = name.lower().replace("/", "\\")
        return key in self.loose() or any(a.has(key) for a in self.archives)
