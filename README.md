# OpenMW Cell Editor

A fast, visual 3D cell editor and furnishing tool for **Morrowind** and **OpenMW** that runs directly in your web browser. 

Fly around cells, place clutter, drop items neatly onto tables, and save changes straight into `.omwaddon` or `.esp` plugins — from your desktop, tablet, or phone.

---

## Quick Start

1. **Launch the Editor**
   - **Pre-built app**: Download the release for Windows, macOS, or Linux and double-click to start.
   - **From source**: Run `python3 cell_editor.py` (requires Python 3.7+; no third-party libraries needed).
   - The start page opens in the editor's own window (the launcher), and the editor opens in your browser. The editor runs until you close the launcher. (From source without `pywebview` installed, the start page opens in your browser too.)

2. **Select or Create a Project**
   - Click **New project** to create a fresh patch or edit an existing `.omwaddon` / `.esp` file in place.
   - The editor automatically reads your game data from `openmw.cfg` or your selected `Data Files` directory.

3. **Decorate and Edit**
   - **Select & Move**: Click any object to show the transform gizmo (`T` move, `R` rotate, `Y` scale), or nudge with arrow keys.
   - **Add Objects**: Right-click any surface or click **Add object...** to place items directly from the categorized 3D catalog.
   - **Smart Cluttering**: Press `G` to drop items cleanly onto surfaces below, and `B` to attach clutter to tables so they move together.
   - **Navigation**: Right-click and drag to look around, or press `Tab` for optional Fly Mode (`WASD`).

4. **Save and Play**
   - Press `Ctrl+S` (or `Cmd+S` on macOS) to save.
   - Enable your plugin in the OpenMW launcher and explore your furnished cell in-game!

---

## Standout Features

- **Intuitive 3D Furnishing**:
  - **Drop onto Surface (`G`)**: Drops hovered clutter directly onto tables, shelves, or floors.
  - **Parent Attachment (`B`)**: Attaches objects to whatever they stand on. Moving the table moves all dishes, cups, and clutter placed on top of it.
  - **Lock Walls & Floors (`L`)**: Prevents accidental selection of walls, ceilings, and floors so you can easily click fine clutter.
  - **Multi-Selection & Groups**: Select multiple objects (`Ctrl/Cmd+Click`) or group them (`Ctrl/Cmd+G`) to manipulate entire furniture arrangements at once.
  - **Visual 3D Catalog**: Searchable object browser with live 3D preview, star favorites, and mod-specific filtering.

- **NPC & Dialogue Editor (Beta)**:
  - **Create & Place NPCs**: Click **Add NPC...** or right-click to place new NPCs with custom name, race, class, level, and starting clothes, or place existing characters from your load order.
  - **Character Customization**: Edit appearance (head, hair), factions, ranks, attributes/skills (or auto-calculate), health/magicka/fatigue, gold, AI behavior (wander, alarm, fight/flee), and merchant services.
  - **Dialogue & Topics**: Add or modify greetings (Greeting 5) and topic responses. Set conditions (journal stages, items, variables, functions) and execution scripts.
  - **Plugin-Safe**: All NPC and dialogue records save cleanly into your plugin, support full undo (`Ctrl/Cmd+Z`), and sync live across connected co-op devices.

- **Mobile & Tablet Companion**:
  - Go to **Settings > Open on another device...** to reveal a local QR code and PIN.
  - Scan with your phone or tablet to furnish your player home from the couch using dedicated virtual thumbsticks and touch controls.

- **Real-Time LAN Co-Op**:
  - Multiple devices or computers on the same local Wi-Fi can join the same project session.
  - See collaborators' live presence markers and colored selection boxes update in real time.

- **Clean & Safe OpenMW Plugins**:
  - Edit existing plugins in place (like OpenMW-CS) or generate clean override patches.
  - Leaves untouched records (NPCs, dialogue, scripts, other cells) byte-for-byte identical.
  - Automatically manages master dependencies and maintains stable reference IDs (`FRMR`).
  - Keeps 10 rolling plugin backups and recovers unsaved drafts if closed accidentally.

- **Zero Clutter, Zero Extra Dependencies**:
  - Built using vanilla Python standard libraries and Three.js. No complex build chains or database setups required.

---

## Controls Reference

### Navigation
| Action | Key / Input |
|---|---|
| Fly forward / back / left / right | `W` `A` `S` `D` |
| Elevation (up / down) | `E` / `Q` |
| Fly faster | `Shift` (hold) |
| Free-look camera | Right-click + Drag (or `Tab` for Fly Mode) |
| Quick Action Menu | Right-click (without dragging) |
| Toggle Fly Mode | `Tab` |

### Manipulation & Placement
| Action | Key / Input |
|---|---|
| Move Gizmo | `T` |
| Rotate Gizmo | `R` |
| Scale Gizmo | `Y` (OpenMW clamps between 0.5 – 2.0) |
| Drop onto Surface | `G` |
| Attach / Detach from Base | `B` |
| Nudge horizontal | Arrow Keys |
| Nudge vertical | `Shift` + `↑` / `↓` (or `PgUp` / `PgDn`) |
| Rotate horizontal | `Z` / `X` |
| Set Move Step | `1` – `6` |
| Focus selected object | `F` |
| Duplicate selected object | `Ctrl + D` (`Cmd + D` on macOS), or right-click > Duplicate |
| Delete selected object | `Delete` or `Backspace` |

### Selection & Editing
| Action | Key / Input |
|---|---|
| Select object | Left Click |
| Multi-select | `Ctrl + Click` (`Cmd + Click` on macOS) |
| Group selected | `Ctrl + G` (`Cmd + G` on macOS) |
| Ungroup | `Ctrl + Shift + G` (`Cmd + Shift + G` on macOS) |
| Select single item in group | `Alt + Click` or Double-Click |
| Deselect all | `Esc` |
| Lock / Unlock Walls & Floors | `L` |
| Undo | `Ctrl + Z` (`Cmd + Z` on macOS) |
| Redo | `Ctrl + Shift + Z` or `Ctrl + Y` (`Cmd + Shift + Z` on macOS) |
| Save Plugin | `Ctrl + S` (`Cmd + S` on macOS) |
| Toggle UI Panel | `P` |

---

## Phone & Tablet (Mobile Companion)

To use your phone or tablet as a wireless controller:
1. Open the editor on your computer.
2. Click **Settings > Open on another device...** (or start with `--lan`).
3. Scan the displayed QR code with your phone or visit the local URL shown.
4. Enter the access code (only needed once per device).

On the phone: the selected object's name and the move / rotate / scale modes are in a bar at the top (in the bottom bar when the phone is on its side); a door that leads somewhere gets a door button left of its name that takes you through it, and an NPC a person button that opens the NPC editor. **Add** asks what: an object or an NPC. The row under the bar rotates, raises, lowers and **Drop**s the object onto the surface below (on its side, also the move arrows). **Multi** selects several objects: taps add them to the selection, **Group** groups them, **Done** brings the gizmo back. Upright, the panel opens from the bottom (drag its top edge to make it taller; a tap beside it closes it); on its side, it opens at the left and the view beside it still takes taps.

> **Note**: Both devices must be on the same local Wi-Fi network. For security, only use this feature on trusted private networks.

---

## Command Line & Running from Source

You can run the editor directly with Python 3.7+ without installing any pip packages:

```bash
# Open start page
python3 cell_editor.py

# Open or create a specific project
python3 cell_editor.py MyHouse.json

# Useful options:
python3 cell_editor.py --port 8765        # Custom port (default 8765)
python3 cell_editor.py --lan              # Enable local network access for phones/tablets
python3 cell_editor.py --cfg <path>       # Specify custom openmw.cfg location
python3 cell_editor.py --data <path>      # Specify custom Data Files directory
python3 cell_editor.py --keep-running     # Keep server alive even after closing browser tabs
python3 cell_editor.py --no-launcher      # The start page in the browser, not in a window of its own
```

---

## System Notes & Permissions

- **macOS**: On first launch of the unsigned app, right-click `OpenMW Cell Editor.app` and choose **Open**, then click **Open Anyway**. macOS will prompt for permission to access protected folders (such as `Documents` or `Desktop`) only when your game or mod files are located there.
- **Windows**: If Windows SmartScreen appears on first run, click **More info** and then **Run anyway**.
- **Stopping**: The editor runs until you close its launcher window (or choose Quit). Without the launcher, it shuts down 20 seconds after you close the last browser tab (extended to 3 minutes if a mobile device is connected).

---

## Building from Source

To package the standalone desktop app:
```bash
python3 -m pip install pyinstaller pywebview
python3 -m PyInstaller packaging/celleditor.spec
```
The output executable will be placed in `dist/`.

---

## AI Usage

This project was developed with the assistance of AI tools because originally I made this as a tool for myself to make my mod developing easier. All the code and functionalities have been reviewed by me and all the features are things I wanted to add to my workflow.

---

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details. Bundles [Three.js](https://threejs.org/) (MIT License).

