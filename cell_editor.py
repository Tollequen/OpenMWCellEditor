"""OpenMW Cell Editor: serves the editor and opens it in the launcher or the browser."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from celleditor import project as projects           # noqa: E402
from celleditor import server                        # noqa: E402
from celleditor.gamedata import GameData             # noqa: E402
from celleditor.settings import Settings             # noqa: E402


def find_game(args, settings, auto=False):
    """The game's files from --data, --cfg or the start page's choice; None if there are none."""
    try:
        if args.data:
            return GameData(args.data)
        if args.cfg:
            return GameData.from_cfg(args.cfg)
        chosen = settings.get("game") or ({"data": settings.get("data_dirs")[0]} if settings.get("data_dirs") else None)
        game = None
        if chosen and chosen.get("cfg"):
            game = GameData.from_cfg(chosen["cfg"])
        elif chosen and chosen.get("data"):
            game = GameData([chosen["data"]])
        if game is not None:
            game.choose(chosen.get("content"))
            return game
        return GameData.from_cfg() if auto else None
    except FileNotFoundError:
        return None


def log_to_file():
    """Send output to editor.log in the settings folder, for a packaged app without a terminal."""
    from celleditor.settings import Settings
    folder = os.path.dirname(Settings().path)
    os.makedirs(folder, exist_ok=True)
    log = open(os.path.join(folder, "editor.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = log


def main():
    frozen = getattr(sys, "frozen", False)
    if frozen and (sys.stdout is None or not sys.stdout.isatty()):
        log_to_file()
    ap = argparse.ArgumentParser(description="OpenMW Cell Editor")
    ap.add_argument("project", nargs="?", help="project file (.json); created if it doesn't exist")
    ap.add_argument("--port", type=int, default=int(os.environ.get("CELLEDITOR_PORT", 8765)))
    ap.add_argument("--lan", action="store_true", help="let other devices on the network connect (with a code), "
                    "also if phone access isn't turned on")
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser")
    ap.add_argument("--no-launcher", action="store_true", help="the start page in the browser too (not in a "
                    "window of its own); the editor stops when its last tab closes")
    ap.add_argument("--data", action="append", help="a Data Files folder (instead of openmw.cfg's)")
    ap.add_argument("--cfg", help="openmw.cfg to read (default: the user's)")
    ap.add_argument("--keep-running", action="store_true",
                    help="don't stop when the last editor tab closes (with --no-browser it doesn't anyway)")
    ap.add_argument("--stop-when-closed", action="store_true", help="stop when the last editor tab closes, "
                    "also with --no-browser")
    args = ap.parse_args([a for a in sys.argv[1:] if not a.startswith("-psn_")])    # macOS may pass -psn_…
    settings = Settings()
    game = find_game(args, settings, auto=bool(args.project))
    p = None
    if args.project:
        if game is None or not game.find("Morrowind.esm"):
            sys.exit("The game's files weren't found. Start the editor with --data \"<Data Files folder>\", "
                     "or without a project to set them on the start page.")
        if not os.path.exists(args.project):
            config = projects.create(args.project)
            print("Created project %s (plugin %s)" % (args.project, config["plugin"]))
        p = projects.load(args.project, game)
    server.run(p, port=args.port, lan=args.lan or bool(settings.get("phone_access")), browser=not args.no_browser,
               code=settings.lan_code(), game=game, settings=settings,
               auto_stop=args.stop_when_closed or not (args.keep_running or args.no_browser),
               gui=not args.no_launcher)


if __name__ == "__main__":
    main()
