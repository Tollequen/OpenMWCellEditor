# PyInstaller spec: python3 -m PyInstaller packaging/celleditor.spec (from the repo folder); output in dist/.
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from celleditor import __version__ as VERSION      # noqa: E402

NAME = "Morrowind Cell Editor"

a = Analysis(
    [os.path.join(ROOT, "cell_editor.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "celleditor", "web"), os.path.join("celleditor", "web"))],
    excludes=["tkinter", "test", "pydoc_data"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME,
          icon=os.path.join(ROOT, "packaging", "icon.ico") if sys.platform == "win32" else None,
          console=sys.platform.startswith("linux"))
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)
if sys.platform == "darwin":
    app = BUNDLE(coll, name=NAME + ".app", bundle_identifier="io.github.tollequen.openmwcelleditor",
                 icon=os.path.join(ROOT, "packaging", "icon.icns"),
                 info_plist={"CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
                             "NSHumanReadableCopyright": "MIT License"})
