"""The launcher: the start page in a pywebview window that keeps the editor running until closed."""
import json
import os

WINDOW = None
FILE_TYPES = {"plugin": ("Content files (*.esm;*.esp;*.omwaddon;*.omwgame)", "All files (*.*)"),
              "project": ("Cell Editor projects (*.json)", "All files (*.*)")}


def available():
    try:
        import webview          # noqa: F401
        return True
    except ImportError:
        return False


class Api:
    """What the start page in the launcher can ask for (window.pywebview.api)."""

    def choose(self, what, start=""):
        """The system's dialog for a folder, content file or project file; the path chosen, or None."""
        import webview
        w = WINDOW
        if w is None or (what != "folder" and what not in FILE_TYPES):
            return None
        start = start or ""
        folder = start if os.path.isdir(start) else os.path.dirname(start) if os.path.isfile(start) else ""
        if what == "folder":
            got = w.create_file_dialog(webview.FileDialog.FOLDER, directory=folder)
        else:
            got = w.create_file_dialog(webview.FileDialog.OPEN, directory=folder, file_types=FILE_TYPES[what])
        return got[0] if got else None


def run(url, serving, storage):
    """Show the start page until the window closes or serving ends."""
    global WINDOW
    import webview
    WINDOW = webview.create_window("OpenMW Cell Editor", url, width=1100, height=820, min_size=(720, 520),
                                   background_color="#1e1f22", js_api=Api())

    def watch():
        serving.join()
        if WINDOW:
            WINDOW.destroy()
    try:
        webview.start(watch, private_mode=False, storage_path=os.path.join(storage, "launcher"))
    finally:
        WINDOW = None


def show(screen="projects", path=None):
    """Bring the launcher to the front on a screen of the start page; False if there's none."""
    w = WINDOW
    if w is None:
        return False
    w.restore()
    w.show()
    # macOS brings a window to the front only with its app; a moment on top does it
    w.on_top = True
    w.on_top = False
    w.evaluate_js("window.launcherShow && launcherShow(%s, %s)" % (json.dumps(screen), json.dumps(path)))
    return True
