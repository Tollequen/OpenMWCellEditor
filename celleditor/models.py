"""Object id -> (record type, mesh), the placeable-object catalog and lights, read from the masters and cached."""
import json
import os
import struct
import sys

from .esp import cstr, esm_records

MODEL_TYPES = ("STAT", "CONT", "ACTI", "DOOR", "LIGH", "MISC", "FURN", "BOOK", "CLOT", "INGR", "APPA",
               "PROB", "LOCK", "REPA", "ALCH", "ARMO", "WEAP", "NPC_", "CREA")
CATALOG_TYPES = {"STAT": "Static", "CONT": "Container", "ACTI": "Activator", "DOOR": "Door", "LIGH": "Light",
                 "MISC": "Misc", "BOOK": "Book", "CLOT": "Clothing", "INGR": "Ingredient", "APPA": "Apparatus",
                 "PROB": "Probe", "LOCK": "Lockpick", "REPA": "Repair", "ALCH": "Potion", "ARMO": "Armor",
                 "WEAP": "Weapon", "NPC_": "NPC"}
VERSION = 5


def cache_dir():
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        base = os.path.join(home, "Library", "Caches")
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(base, "OpenMWCellEditor")


def _scan(path):
    models, catalog, lights = {}, [], {}
    for tag, _, subs in esm_records(path):
        if tag not in MODEL_TYPES or not subs or subs[0][0] != "NAME":
            continue
        oid = cstr(subs[0][1])
        d = dict(subs)
        if tag == "LIGH" and len(d.get("LHDT", b"")) >= 24:
            # LHDT: weight, value, time, radius, colour (RGBA bytes), flags
            radius, r, g, b, _, flags = struct.unpack_from("<i4BI", d["LHDT"], 12)
            lights[oid.lower()] = [radius, r, g, b, flags]
        # most NPCs have no MODL: they use their race's body parts; a light without one still shines
        if "MODL" not in d and tag not in ("NPC_", "LIGH"):
            continue
        mesh = cstr(d.get("MODL", b""))
        models[oid.lower()] = (tag, mesh)
        if tag in CATALOG_TYPES and (mesh or tag == "NPC_") and not mesh.lower().endswith("editormarker.nif"):
            catalog.append({"id": oid, "type": CATALOG_TYPES[tag], "name": cstr(d.get("FNAM", b"")),
                            "mesh": "" if tag == "NPC_" else mesh,       # an NPC's MODL is an animation, not its mesh
                            "file": os.path.basename(path)})
    return models, catalog, lights


def load(masters):
    """(models, catalog, origins, lights) of the content files, later ones overriding earlier ones.

    lights: {id (lower case): [radius, red, green, blue, flags]}."""
    models, catalog, origins, lights = {}, {}, {}, {}
    for path in masters:
        st = os.stat(path)
        key = "%s-%d-%d" % (os.path.basename(path).lower(), st.st_size, int(st.st_mtime))
        cache = os.path.join(cache_dir(), "models-%s.json" % key)
        data = None
        try:
            with open(cache) as f:
                data = json.load(f)
            if data.get("version") != VERSION:
                data = None
        except (OSError, ValueError):
            pass
        if data is None:
            m, c, li = _scan(path)
            data = {"version": VERSION, "models": m, "catalog": c, "lights": li}
            try:
                os.makedirs(cache_dir(), exist_ok=True)
                with open(cache + ".tmp", "w") as f:
                    json.dump(data, f)
                os.replace(cache + ".tmp", cache)
            except OSError:
                pass
        name = os.path.basename(path)
        for k, v in data["models"].items():
            models[k] = tuple(v)
            origins.setdefault(k, name)
        for o in data["catalog"]:
            catalog[o["id"].lower()] = dict(o, file=origins.get(o["id"].lower(), name))
        lights.update(data["lights"])
    return models, sorted(catalog.values(), key=lambda o: o["id"].lower()), origins, lights
