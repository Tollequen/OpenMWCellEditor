# Morrowind Cell Editor

A fast, visual 3D cell editor and furnishing tool for **Morrowind** and **OpenMW** that runs directly in your web browser. 

Fly around cells, place clutter, drop items neatly onto tables, and save changes straight into `.omwaddon` or `.esp` plugins — from your desktop or phone or in Co-op with a friend.

---

## Quick Start

1. **Launch the Editor**
   - **Pre-built app**: Download the release for Windows, macOS, or Linux.
   - **From source**: Run `python3 cell_editor.py` (requires Python 3.7+; no third-party libraries needed).
   - The start page opens in the editor's own window (the launcher), and the editor opens in your browser. The editor runs until you close the launcher.

2. **Select or Create a Project**
   - Click **New project** to create a new patch or edit an existing `.omwaddon` / `.esp` file.
   - The editor automatically reads your game data from `openmw.cfg` or your selected `Data Files` directory.

3. **Decorate and Edit**
   - **Select & Move**: Click any object to show the transform gizmo (`T` move, `R` rotate, `Y` scale), or nudge with arrow keys.
   - **Add Objects**: Right-click any surface or click **Add object...** to place items directly from the categorized 3D catalog.
   - **Smart Cluttering**: Press `G` to drop items cleanly onto surfaces below, and `B` to attach clutter to tables so they move together.
   - **Navigation**: Right-click and drag to look around, or press `Tab` for optional Fly Mode.

4. **Save and Play**
   - Press `Ctrl+S` (or `Cmd+S` on macOS) to save.
   - Enable your plugin in the OpenMW launcher.

---

## Standout Features

- **Intuitive 3D Furnishing**:
  - **Drop onto Surface (`G`)**: Drops hovered clutter directly onto tables, shelves, or floors.
  - **Parent Attachment (`B`)**: Attaches objects to whatever they stand on. Moving the table moves all dishes, cups, and clutter placed on top of it.
  - **Lock Walls & Floors (`L`)**: Prevents accidental selection of walls, ceilings, and floors so you can easily click fine clutter.
  - **Multi-Selection & Groups**: Select multiple objects (`Ctrl/Cmd+Click`) or group them (`Ctrl/Cmd+G`) to manipulate entire furniture arrangements at once.
  - **Visual 3D Catalog**: Searchable object browser with live 3D preview, a grid of model pictures, star favorites, and mod-specific filtering.
  - **Simulate Lighting**: See a cell lit as in OpenMW (its own ambient light and every light source's colour and radius) instead of the editor's even light, and watch it change as you move lights. Exteriors show a clear night.

- **NPC & Dialogue Editor (Beta)**:
  - **Create & Place NPCs**: Click **Add NPC...** or right-click to create new NPCs.
  - **Character Customization**: Edit appearance (head, hair), factions, ranks, attributes/skills, inventory, AI behavior, and merchant services.
  - **Dialogue & Topics**: Add or modify greetings and topic responses. Set conditions (journal stages, items, variables, functions) and execution scripts.

- **Mobile Version**:
  - Go to **Settings > Open on another device...** to reveal a local QR code and PIN.
  - Scan with your phone or tablet to use the editor with touch controls.

- **Real-Time LAN Co-Op**:
  - Multiple devices or computers on the same local Wi-Fi can join the same project session.
  - See collaborators' live presence markers and colored selection boxes update in real time.

- **Clean & Safe OpenMW Plugins**:
  - Edit existing plugins in place (like OpenMW-CS) or generate clean override patches.
  - Leaves untouched records (NPCs, dialogue, scripts, other cells) byte-for-byte identical.
  - Automatically manages master dependencies and maintains stable reference IDs (`FRMR`).
  - Keeps 10 rolling plugin backups and recovers unsaved drafts if closed accidentally.

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

## Mobile connection and Co-Op

To use your phone or tablet to edit:
1. Open the editor on your computer. You need to have the project running there.
2. In the editor click **Open on another device...**.
3. Scan the displayed QR code with your phone or visit the local URL shown.
4. Enter the access code if asked.

> **Note**: All devices must be on the same local Wi-Fi network. For security, only use this feature on trusted private networks. Multiplayer over internet is possible, but this tool does not provide secure connections for that.

---

## AI Usage

This project was developed with the assistance of AI tools because originally I made this as a tool for myself to make my mod developing easier. All the code and functionalities have been reviewed by me and all the features are things I wanted to add to my workflow.

---

## Building from Source

You can run the editor directly without building, or package it into a standalone application:

### Run directly with Python (No build needed)
Requires Python 3.7+ (uses only Python's standard library):
```bash
python3 cell_editor.py
```

### Build standalone executables
1. Install build requirements:
   ```bash
   pip install pyinstaller pywebview
   ```
2. Build using the included PyInstaller spec:
   ```bash
   pyinstaller packaging/celleditor.spec
   ```
   The output application will be generated in `dist/`.

---

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details. Bundles [Three.js](https://threejs.org/) (MIT License).

