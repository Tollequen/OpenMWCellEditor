"""Projects: the plugin the editor edits, described by a JSON project file."""
import datetime
import hashlib
import importlib.util
import io
import json
import os
import shutil
import struct
import sys
from contextlib import redirect_stdout

from . import dialogue as dial, esp, launcher, loadorder, models, npc, writer

DEFAULTS = {
    "name": None,
    "plugin": None,
    "masters": ["Morrowind.esm"],
    "description": "",
    "author": "",
    "edits": "layout_edits.json",
    "history": "layout_history",
    "favorites": "layout_favorites.json",
    "refnums": "layout_refnums.json",
    "start_cell": "Seyda Neen, Arrille's Tradehouse",
    "content": None,
    "generator": None,
    "base": None,
    "data_files": None,
    "load_order": None,
    "folders": None,
    "base_order": None,
    "standalone": False,
}

OFFICIAL = ("morrowind.esm", "tribunal.esm", "bloodmoon.esm")
OFFICIAL_NAMES = set(OFFICIAL)


class Project:
    own_cells = ()
    nooks = {}
    fixed_masters = False

    def __init__(self, path, config, game):
        self.path = os.path.abspath(path)
        self.dir = os.path.dirname(self.path)
        self.config = dict(DEFAULTS, **config)
        self.game = game
        self.name = self.config["name"] or os.path.splitext(os.path.basename(self.config["plugin"]))[0]
        self.in_place = bool(self.config["base"])
        self.notice = None
        mine = os.path.basename(self.config["plugin"])
        if self.in_place:
            self.notice = self._check_base()
            self.masters = [game.master(m) for m in loadorder.masters_of(self.file("base"))]
            load = loadorder.from_game(game, self.config["content"], replace={mine: self.file("base")})
        else:
            self.masters = [game.master(m) for m in self.config["masters"]]
            load = loadorder.from_game(game, self.config["content"], [mine])
        self.master = self.masters[0] if self.masters else None
        loaded = {f.name.lower() for f in load.files}
        missing = [m for m in self.masters if os.path.basename(m).lower() not in loaded]
        self.load = loadorder.LoadOrder(missing + load.paths) if missing else load
        self._origins = self._npcs = self._dialogue = None
        content = [c.lower() for c in (self.config["content"] or game.all_content)]
        mine = mine.lower()
        self.loads_after = set(content[content.index(mine) + 1:]) if mine in content else set()
        names = [f.name.lower() for f in self.load.files]
        self.before = set(names[:names.index(mine) + 1]) if self.in_place and mine in names else None

    def file(self, key):
        """A project path from the config, made absolute."""
        return os.path.join(self.dir, self.config[key])

    @property
    def plugin(self):
        return self.file("plugin")

    edits_override = None
    new_masters = ()

    def load_edits(self):
        if self.edits_override is not None:
            return json.loads(json.dumps(self.edits_override))
        return writer.load_edits(self.file("edits"))

    def master_refs(self, cell):
        """A cell's references in the load order, as refs the edits can change."""
        return self.load.master_refs(cell, os.path.basename(self.master) if self.master else "Morrowind.esm")

    def master_names(self):
        return {os.path.basename(m).lower() for m in self.masters}

    def usable_files(self):
        """The files whose objects and cells the plugin may use (lower case), or None for any."""
        if self.fixed_masters:
            return self.master_names()
        files = self.before
        if self.config["standalone"]:
            own = OFFICIAL_NAMES | self.master_names() | {os.path.basename(self.config["plugin"]).lower()}
            files = own if files is None else files & own
        return files

    def can_edit(self, r):
        """Whether a reference may be changed."""
        files = self.usable_files()
        return files is None or not r.get("origin") or r["origin"].lower() in files

    def can_add(self, cell):
        """Whether objects may be added to a cell."""
        files = self.usable_files()
        if files is None or cell in self.own_cells or (self.in_place and esp.parse_exterior(cell)):
            return True
        return self.load.has_cell(cell, among=files)

    # --- NPCs -------------------------------------------------------------------

    @property
    def can_edit_npcs(self):
        """Whether NPCs can be edited: not when a generator writes the plugin itself."""
        return type(self).write_plugin is Project.write_plugin

    def npcs(self):
        """The load order's NPCs and what their fields choose from."""
        if self._npcs is None:
            self._npcs = npc.Index(*self._records_load())
        return self._npcs

    def npc_records(self):
        """The edited and new NPCs' records and the files they need."""
        edits = self.load_edits().get("npcs") or {}
        if not edits:
            return [], {}
        return self.npcs().records(edits)

    def dialogue(self):
        """The load order's topics and responses, merged."""
        if self._dialogue is None:
            self._dialogue = dial.Dialogue(*self._records_load())
        return self._dialogue

    def dialogue_records(self):
        """The edited topics' DIAL + INFO groups and the files they need."""
        edits = self.load_edits().get("dialogue") or {}
        if not edits:
            return {}, {}
        return self.dialogue().records(edits, os.path.basename(self.plugin)
                                       if self.in_place or self.builds_base else None)

    def records_and_needs(self):
        """The plugin's NPC records and dialogue groups, and the files they need."""
        npcs, need = self.npc_records()
        groups, more = self.dialogue_records()
        need = {k: list(v) for k, v in need.items()}
        for k, v in more.items():
            need.setdefault(k, []).extend(v)
        return npcs, groups, need

    def _records_load(self):
        """(load order, usable files) for the NPC and dialogue editors."""
        if not self.builds_base:
            return self.load, self.usable_files()
        gen = self.generated_plugin
        folder = os.path.dirname(self.file("generator")) if self.config["generator"] else None
        scripts = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".py")] if folder else []
        if not os.path.exists(gen) or any(os.path.getmtime(f) > os.path.getmtime(gen) for f in scripts):
            self._build_base()
        usable = {m.lower() for m in loadorder.masters_of(gen)} | {os.path.basename(gen).lower()}
        return loadorder.LoadOrder(self.load.paths + [gen]), usable

    # --- A generator's plugin, with the NPC and dialogue edits -----------------------

    @property
    def builds_base(self):
        return type(self).build_base is not Project.build_base

    @property
    def generated_plugin(self):
        """Where build_base writes the plugin."""
        return os.path.join(self.file("history"), "generated", os.path.basename(self.plugin))

    def _build_base(self):
        """Run build_base with the saved edits."""
        os.makedirs(os.path.dirname(self.generated_plugin), exist_ok=True)
        esp.release()                             # Windows can't replace a file that's mapped
        self._npcs = self._dialogue = None
        override, self.edits_override = self.edits_override, None
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                self.build_base(self.generated_plugin)
        finally:
            self.edits_override = override
        said = out.getvalue().replace(self.generated_plugin, self.plugin).strip()
        if said:
            print(said)

    def _write_generated(self):
        self._build_base()
        gen = self.generated_plugin
        npcs, topics, _ = self.records_and_needs()
        masters = [self.game.master(m) for m in loadorder.masters_of(gen)]
        exteriors = self.load.cells()[1]
        key_of = lambda g: esp.exterior_key(g, exteriors.get(g, ""))     # noqa: E731
        data, _, _ = writer.rewrite_plugin(gen, {}, {}, writer.RefNums(), masters, self._cell_key(key_of), key_of,
                                           None, None, {("NPC_", k): rec for k, rec in npcs}, topics)
        writer.write_file(self.plugin, data)
        return "wrote %s%s" % (os.path.basename(self.plugin), _npcs_text(npcs, topics)) if npcs or topics else ""

    # --- Editing a plugin in place ------------------------------------------------

    def _check_base(self):
        """Start over from the plugin if it changed outside the editor; returns a message or None."""
        plugin, base = self.plugin, self.file("base")
        if not os.path.exists(plugin):
            return None if os.path.exists(base) else "%s isn't there any more." % os.path.basename(plugin)
        now = _sha1(plugin)
        if not os.path.exists(base) or now in (self.config.get("written"), _sha1(base)):
            return None
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        old = self.file("history")
        if os.path.isdir(old):
            os.rename(old, "%s (before %s)" % (old, stamp))
        if os.path.exists(self.file("edits")):
            os.replace(self.file("edits"), "%s (before %s).json" % (os.path.splitext(self.file("edits"))[0], stamp))
        esp.release()
        shutil.copy2(plugin, base)
        refnums = writer.RefNums(self.file("refnums"))
        if refnums.refs:
            refnums.refs, refnums.changed = {}, True
            refnums.save()
        return ("%s was modified outside the editor and has been reloaded. "
                "Earlier history was backed up to \"%s (before %s)\"." % (
                    os.path.basename(plugin), os.path.basename(old), stamp))

    def _save_config(self):
        with open(self.path) as f:
            config = json.load(f)
        config["written"] = self.config.get("written")
        with open(self.path, "w") as f:
            json.dump(config, f, indent=1)

    def write_in_place(self):
        cells, vanilla, _ = self.gather()
        npcs, topics, extra_need = self.records_and_needs()
        exteriors = self.load.cells()[1]
        key_of = lambda g: esp.exterior_key(g, exteriors.get(g, ""))     # noqa: E731
        writer.rehome_exterior_refs(cells, vanilla, key_of)
        mine = os.path.basename(self.plugin).lower()
        need = {m.name.lower() for m in self.plugin_masters(cells, vanilla, extra_need)} - {mine}
        old = [os.path.basename(m).lower() for m in self.masters]
        masters = self.masters + [f.path for f in self.load.files if f.name.lower() in need - set(old)]
        index = {os.path.basename(m).lower(): i for i, m in enumerate(masters)}
        self._new_masters(masters, cells, vanilla, extra_need)

        def head_of(cell):
            try:
                return self.load.cell_head(cell, among=[os.path.basename(m) for m in masters])
            except KeyError:
                if not esp.parse_exterior(cell):
                    raise
                return writer.exterior_head(esp.parse_exterior(cell))

        refnums = writer.RefNums(self.file("refnums"))
        data, written, count = writer.rewrite_plugin(
            self.file("base"), cells, vanilla, refnums, masters, self._cell_key(key_of), key_of, head_of,
            lambda r: index[r["origin"].lower()], {("NPC_", k): rec for k, rec in npcs}, topics)
        writer.write_file(self.plugin, data)
        refnums.save()
        self.config["written"] = hashlib.sha1(data).hexdigest()
        self._save_config()
        return "wrote %s: %d cells changed, %d new references%s (masters: %s)%s" % (
            os.path.basename(self.plugin), written, count, _npcs_text(npcs, topics),
            ", ".join(os.path.basename(m) for m in masters), self._new_masters_text())

    @staticmethod
    def _cell_key(key_of):
        """A CELL record's cell name from its header subrecords."""
        def cell_key(head):
            d = dict(head)
            flags = struct.unpack_from("<I", d["DATA"])[0]
            if flags & 1:
                return esp.cstr(d["NAME"])
            return key_of(struct.unpack_from("<ii", d["DATA"], 4))
        return cell_key

    def origins(self):
        """{object id (lower case): the file that defines it}."""
        if self._origins is None:
            self._origins = models.load(self.load.paths)[2]
        return self._origins

    # --- Hooks (generators override these) -----------------------------------

    def generated(self):
        """{cell: [refs]}: the project's own references before the edits."""
        return {}

    def clones(self):
        """{object id: id of the object whose mesh it uses}, for the project's copies."""
        return {}

    def extra_models(self):
        """{object id (lower case): (record type, mesh)} for the project's own objects."""
        return {}

    def structure_ids(self):
        """Ids of the project's own building pieces."""
        return set()

    def build_base(self, path):
        """Write the plugin to path: its cells with the layout edits, and its own records."""
        raise NotImplementedError

    def tier(self, obj_id):
        """(nook, tier, only at that tier) of an upgrade-tier object, or None."""
        return None

    def start(self, cell):
        """((x, y, z), heading) where the camera starts in a cell, or None."""
        return None

    def water(self, cell):
        """The water level of a project's own cell, None for no water; KeyError to use the master's."""
        raise KeyError(cell)

    def added_id(self, a):
        """The object id written for an added object."""
        return a["id"]

    def replaced_id(self, old, new):
        """The object id written when an object is changed to another."""
        return new

    # --- Building ---------------------------------------------------------------

    def gather(self, extra_cells=()):
        """({cell: refs}, {cell: master refs}, keys) with the edits applied."""
        return writer.gather(self.generated(), self.load_edits(), self.master_refs, extra_cells,
                             self.added_id, self.replaced_id)

    def plugin_masters(self, cells, vanilla, extra_need=()):
        """The plugin's masters, in load order."""
        need = self.master_names()
        if not self.fixed_masters:
            need |= {n.lower() for n in extra_need}
            origins = self.origins()
            for name in set(cells) | set(vanilla):
                changed = [r for r in vanilla.get(name, []) if r["changed"]]
                if not cells.get(name) and not changed:
                    continue
                for r in changed:
                    need.add(r["origin"].lower())
                    need.add(origins.get(r["id"].lower(), r["origin"]).lower())
                for r in cells.get(name, []):
                    if r["id"].lower() in origins:
                        need.add(origins[r["id"].lower()].lower())
                files = self.load.defining(name)
                if files and not any(f.name.lower() in need for f in files):
                    need.add(files[0].name.lower())
        return [f for f in self.load.files if f.name.lower() in need]

    def _new_masters(self, masters, cells, vanilla, extra_need=None):
        """The masters the plugin didn't have before: [(file name, [reasons])]."""
        extra_need = {k.lower(): v for k, v in (extra_need or {}).items()}
        old_file = self.file("base") if self.in_place else self.plugin
        try:
            old = {m.lower() for m in loadorder.masters_of(old_file)} if os.path.exists(old_file) else set()
        except (OSError, StopIteration):
            old = set()
        new = [os.path.basename(m) for m in masters if os.path.basename(m).lower() not in old | OFFICIAL_NAMES]
        origins = self.origins()
        out = []
        for name in new:
            why = []
            for cell, refs in cells.items():
                for r in refs:
                    if origins.get(r["id"].lower(), "").lower() == name.lower():
                        why.append("%s placed in %s" % (r["id"], cell))
            for cell, refs in vanilla.items():
                for r in refs:
                    if r["changed"] and r["origin"].lower() == name.lower():
                        why.append("%s %s in %s" % (r["id"], "deleted" if r["deleted"] else "changed", cell))
                    elif r["changed"] and origins.get(r["id"].lower(), "").lower() == name.lower():
                        why.append("%s changed in %s" % (r["id"], cell))
            why += extra_need.get(name.lower(), [])
            if not why:
                why = ["a cell of it is changed"]
            out.append((name, why[:3] + (["and %d more" % (len(why) - 3)] if len(why) > 3 else [])))
        self.new_masters = out
        return out

    def _new_masters_text(self):
        names = [n for n, _ in self.new_masters]
        if not names:
            return ""
        return "\nNow it also needs %s." % (" and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1])

    def write_plugin(self):
        """Write the plugin; returns a status message."""
        if self.in_place:
            return self.write_in_place()
        if self.builds_base:
            return self._write_generated()
        cells, vanilla, _ = self.gather()
        npcs, topics, extra_need = self.records_and_needs()
        exteriors = self.load.cells()[1]
        writer.rehome_exterior_refs(cells, vanilla, lambda g: esp.exterior_key(g, exteriors.get(g, "")))
        masters = self.plugin_masters(cells, vanilla, extra_need)
        self._new_masters([m.path for m in masters], cells, vanilla, extra_need)
        names = [m.name for m in masters]
        index = {n.lower(): i for i, n in enumerate(names)}
        refnums = writer.RefNums(self.file("refnums"))
        def head_of(cell):
            try:
                return self.load.cell_head(cell, among=names)
            except KeyError:
                if not esp.parse_exterior(cell):
                    raise
                return writer.exterior_head(esp.parse_exterior(cell))
        records, count = writer.edited_cell_records(cells, vanilla, None, refnums, head_of=head_of,
                                                    master_index=lambda r: index[r["origin"].lower()])
        writer.write_file(self.plugin, writer.plugin_bytes([rec for _, rec in npcs] + records + list(topics.values()),
                                                           [m.path for m in masters],
                                                           self.config["description"], self.config["author"]))
        refnums.save()
        return "wrote %s with %d cells and %d new references%s (masters: %s)%s" % (
            os.path.basename(self.plugin), len(records), count, _npcs_text(npcs, topics), ", ".join(names),
            self._new_masters_text())

    def backup_plugin(self, keep=10):
        """Back up the plugin into the history folder before it's written again."""
        if not os.path.exists(self.plugin):
            return None
        folder = os.path.join(self.file("history"), "plugin-backups")
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dest = os.path.join(folder, "%s_%s" % (stamp, os.path.basename(self.plugin)))
        shutil.copy2(self.plugin, dest)
        old = sorted(f for f in os.listdir(folder) if f.endswith(os.path.basename(self.plugin)))
        for f in old[:-keep]:
            os.remove(os.path.join(folder, f))
        return dest

    def build(self):
        """Back up the plugin, write it again and return its output."""
        self.backup_plugin()
        out = io.StringIO()
        with redirect_stdout(out):
            msg = self.write_plugin()
        return "\n".join(s for s in (out.getvalue().strip(), msg or "") if s)


def _npcs_text(npcs, topics=()):
    out = ", %d NPC%s" % (len(npcs), "" if len(npcs) == 1 else "s") if npcs else ""
    if topics:
        out += ", %d topic%s" % (len(topics), "" if len(topics) == 1 else "s")
    return out


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def create_in_place(folder, plugin, setup=None):
    """A project that edits an existing plugin in place."""
    name = os.path.basename(plugin)
    if name.lower() in OFFICIAL:
        raise ValueError("%s is one of the game's own files: make a new content file that changes it instead." % name)
    stem = os.path.splitext(name)[0]
    base = os.path.join(folder, "base", name)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    shutil.copy2(plugin, base)
    interiors, exteriors, names = esp.cell_index(base)
    config = dict({"name": stem, "plugin": os.path.abspath(plugin), "base": os.path.join("base", name)}, **(setup or {}))
    if interiors:
        config["start_cell"] = sorted(interiors)[0]
    path = os.path.join(folder, stem + ".json")
    with open(path, "w") as f:
        json.dump(config, f, indent=1)
    return path


def create_new(folder, plugin, setup=None):
    """A project that makes a new plugin."""
    if os.path.exists(plugin):
        raise ValueError("There's already a file %s." % plugin)
    stem = os.path.splitext(os.path.basename(plugin))[0]
    os.makedirs(folder, exist_ok=True)
    config = dict({"name": stem, "plugin": os.path.abspath(plugin), "masters": ["Morrowind.esm"]}, **(setup or {}))
    path = os.path.join(folder, stem + ".json")
    with open(path, "w") as f:
        json.dump(config, f, indent=1)
    return path


def create(path, plugin=None):
    """Write a new project file for a plugin."""
    stem = os.path.splitext(os.path.basename(path))[0]
    if stem.lower() in ("project", "celleditor"):
        stem = os.path.basename(os.path.dirname(os.path.abspath(path))) or "MyPlugin"
    config = {"name": stem, "plugin": plugin or stem + ".omwaddon", "masters": ["Morrowind.esm"]}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=1)
    return config


def load(path, game):
    """The project in a project file, with its generator's Project class if it has one."""
    with open(path) as f:
        config = json.load(f)
    game = launcher.game_for(config) or game
    if game is None:
        raise FileNotFoundError("The game's files weren't found (no openmw.cfg).")
    cls = Project
    if config.get("generator"):
        gen = os.path.join(os.path.dirname(os.path.abspath(path)), config["generator"])
        sys.path.insert(0, os.path.dirname(gen))
        spec = importlib.util.spec_from_file_location("celleditor_generator", gen)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = module.Project
    return cls(path, config, game)
