# Changelog

All notable changes to Morrowind Cell Editor are documented in this file.

## [Unreleased]

- **New panel layout**: the panel in sections: Save beside undo and redo (blue while there are unsaved changes), Add to the cell, the selected object with Move / Rotate / Scale and its actions, View switches (Lock walls, Simulate lighting) and the project.
- **Simulate lighting**: a button next to Lock walls lights the cell as OpenMW does: the cell's ambient and sunlight, and each light's colour and radius with the falloff from openmw.cfg. Lights update as they are moved, added or removed. Exteriors show a clear night.
- **Choose first, then place**: Add object… opens the object list at once, and Add NPC… names the new NPC (or picks an existing one) first; it is placed where you click next.
- **Restoring unsaved changes can be undone**: after Restore changes, Undo goes back to the saved plugin.
- **Back where you were**: the object list opens on the object picked last time (as well as the category).
- **Model grid**: the object list can show the models as pictures (the list and grid buttons next to Category).
- **NPCs aren't duplicated**: Duplicate skips NPCs (it would place the same NPC twice); Copy as new NPC… makes a separate one.
- **Copy as new NPC**: one undo step for the new NPC and its placement; copies of upgrade-tier NPCs save correctly.
- **Messages**: "Saving…" stays until the result comes; reconnecting ends with "Connected again."
- **Recent objects**: the object list has a Recent category: the last 20 objects added or swapped in, newest first.
- **Only the host manages projects**: other devices edit the open project, but opening, creating, deleting and setting up projects, browsing the host's folders and quitting are done on the host.
- **Greetings**: choosing Greeting 5 (or a topic) from the list adds it at once; shorter explanations of what each greeting is for.
- **Connection lost**: a short "Connection to host lost" that reconnects by itself.
- **Suggestions while typing**: item, spell, script, topic and quest fields suggest up to 50 matches once two letters are typed, instead of a long cut-off list.
- **The whole object list**: every object of a category can be browsed; more rows load while scrolling.
- **Tier of an added object**: projects with upgrade tiers can change the tier of a selected object added in the editor.

## [0.3.0] - 2026-10-01

- **New name**: Morrowind Cell Editor (was OpenMW Cell Editor). Projects and settings stay where they were.
- **File type for new content files**: `.omwaddon` (OpenMW), `.esp` or `.esm` (a master file, marked as one in its header).
- **Construction Set cell layout**: rebuilt cells list persistent references (NPCs, creatures, doors that teleport) first, then the `NAM0` marker and the rest, as the original Construction Set writes them.

## [0.2.0] - 2026-09-30

Initial standalone release of **Morrowind Cell Editor** — a visual 3D cell editor and furnishing tool for Morrowind and OpenMW that runs directly in your web browser.

### Key Highlights
- **In-Place Mod Editing**: Edit existing `.omwaddon` or `.esp` plugins directly (like OpenMW-CS), or create new override patches without modifying base game files.
- **Smart Furnishing Tools**: Rapidly place clutter, drop objects cleanly onto surfaces (`G`), and attach items to whatever they stand on (`B`) so they move together with furniture.
- **NPC & Dialogue Editor (Beta)**: Create, place, and customize NPCs directly in your cells. Edit appearance, stats, factions, AI behavior, merchant services, and dialogue responses.
- **Mobile & Tablet Companion**: Decorate your player home from your phone or tablet over local Wi-Fi with dedicated touch controls.
- **Real-Time LAN Co-Op**: Collaborate with others on your home network simultaneously, with live presence markers and synchronized changes.

### Editor & 3D Viewport
- **Right-Click Quick Menu**: Right-click any surface to add objects or NPCs directly at the mouse cursor and access context actions.
- **Object Duplication (`Ctrl/Cmd+D`)**: Duplicate single objects, selections, or entire attached assemblies with clean automatic positioning.
- **Fly Navigation**: Free-cam navigation (WASD + mouse look, Tab to toggle Fly mode, Q/E for vertical movement, Shift for speed boost).
- **Transform Gizmos**: Move, rotate, and scale gizmos with customizable snap steps.
- **Multi-Selection & Grouping**: Select multiple items (Ctrl/Cmd+Click) to move, rotate, or scale together; create persistent groups (Ctrl/Cmd+G).
- **Lock Walls & Floors**: Protect architectural pieces (`L`) so clicks reliably select furniture and clutter in front of them without picking the wall behind.
- **Door Linking**: Inspect door destinations, teleport to target cells, and set arrival positions and orientations visually.
- **3D Catalog & Previews**: Filterable object catalog with interactive 3D mesh previews, favorite stars, and mod-specific categorization.
- **Visual Rollback & Undo**: Per-device undo/redo and a visual history panel to inspect earlier saves or revert specific objects.

### NPC & Dialogue Editor (Beta)
- **Create & Place Characters**: Place new NPCs at any position with automatic ID generation, customizable name, race, class, level, and starting clothing.
- **Character Customization**: Configure appearance (heads, hair), factions/ranks, auto-calculated stats, health/magicka/fatigue, gold, AI settings (wander, alarm, fight/flee), and merchant services.
- **Dialogue & Greetings**: Add and modify greeting responses (Greeting 5) and topic dialogue. Filter by conditions (journal quest stages, items, variables) and attach result scripts.
- **Cell NPC Management**: Inspect and manage all NPCs in the current cell from a dedicated window.

### Plugin Management & Safety
- **Clean In-Place Rewrites**: Preserves untouched records (NPCs, dialogue, scripts, unmodified cells) byte-for-byte; only modified cells are rewritten.
- **Automated Master Tracking**: Plugins only adopt new masters when their assets or references are actually used, with clear notifications upon saving.
- **Stable Reference Numbers (FRMR)**: Persistent tracking ensures deleted reference IDs are never reused and save-game compatibility is maintained.
- **Exterior Border Tracking (MVRF)**: Automatically tracks and updates objects moved across exterior cell boundaries.
- **Conflict Detection**: Warns when another plugin in your load order modifies the same reference or cell.
- **Automatic Backups & Recovery**: Automatically keeps rolling backups of the last 10 saves; preserves unsaved drafts if a tab or the server closes unexpectedly.

### Mobile, Tablet & LAN Co-Op
- **Instant QR Pairing**: Enable local network access in settings to display a QR code and local IP address protected by a PIN code.
- **Dedicated Touch Controls**: Virtual thumbstick, camera swipe, elevation buttons, and quick action bar designed for phone and tablet screens.
- **Multi-User Sync**: Edit the same cell at the same time across multiple devices via Server-Sent Events (SSE). See peer presence markers, selections, and edits live.
- **Graceful Lifecycle**: Background server automatically shuts down cleanly after closing browser tabs (with an extended grace window for mobile devices).

### Engine & System Compatibility
- **OpenMW Load Order Integration**: Reads data directories, BSAs, and content files directly from `openmw.cfg`.
- **Large Mod Support**: Memory-mapped parsing handles large mods like Tamriel Rebuilt and Tamriel Data smoothly (including meshes with switch nodes and subfolder textures).
- **Zero-Dependency Core**: Python backend runs entirely on standard library (Python 3.7+); no external Python packages required.
- **Standalone Desktop App**: Bundled executable builds available for Windows, macOS, and Linux (no Python installation required).
