# Manual test checklist

Everything that was added or changed on the `composer-look-and-feel` branch and that is worth
checking by hand. The automated tests (`uv run pytest`, see [DEV.md](../DEV.md)) drive the
application headless with simulated mouse and keys; they cannot see a real screen, a real trackpad,
the operating system's file watcher or native menus. Items marked **🖥** can only be confirmed here.

Each item reads: *what to do* → *what should happen*. Tick it when it does. Note the item id
(for example `B-07`) when something does not, with the platform and the exact steps.

## How to use this list

1. Start with section **A** (things only real hardware can confirm), then go through the sections of
   the features you care about. Section **R** is a quick pass over older behaviour, **S** covers the `*` marker and the save prompt, **O** the remote folders over SSH (only on the `ssh-remote-folders` branch), **P** the logo that shows at the start, **U** running a document from the editor, **V** the Problems panel, live checks and autocompletion of the Code tab, **W** Fix with AI for validation errors, **X** the container assistant of the Docker image field, and **T** the tests and documentation.
2. Use a scratch copy of the test documents, so that saving never touches the repository (outside the temporary directory, see below):

   ```bash
   cp -R tests ~/cwled-manual && cd ~/cwled-manual
   git init -q && git add . && git commit -qm "first version"      # for the comparison checks (H)
   cd -
   uv run ./cwled.py --workspace ~/cwled-manual
   ```

   Keep the scratch copy **outside the operating system's temporary directory** (not `/tmp`, not `/var/folders/…`): the editor treats every document
   under it as temporary, so the tab then shows the document's label instead of the file name, which looks like a bug in the checks below.

3. The documents used below (all in `tests/`):

   | file | what it is |
   |---|---|
   | `echo.cwl`, `uppercase.cwl`, `01-hello-world.cwl`, `05-input.cwl`, `07-record.cwl` | small tools |
   | `50-workflow.cwl` | a workflow whose two steps run the files `echo.cwl` and `uppercase.cwl` |
   | `51-workflow.cwl` | a workflow whose two steps are defined **inside** the file |
   | `60-test-record-wflow.cwl` | a bigger workflow |

4. Useful extra set-up:
   - a second workspace folder (**File → Add Folder to Workspace…**), for example `docs/`;
   - a hidden folder: open `50-workflow.cwl` and run **Tools → Repackage workflow with all tools**
     (it writes the tools under `.steps`);
   - a folder with many sub-folders (your real project), for the speed checks;
   - the same workflow in two versions: copy `50-workflow.cwl` to `v2.cwl`, add `label: Shout it` to
     the `uppercase` step and an input `extra: int`.

Keyboard: **Cmd** on macOS is **Ctrl** elsewhere; the document says "Cmd/Ctrl".

---

## A. Only real hardware can confirm 🖥 (do these first)

### Dragging tabs and windows

- [ ] **A-01** Drag a document tab about 30 px below (or above) the tab bar → a window appears under
      the cursor, follows the mouse smoothly while translucent, and stays where you release it.
      The cursor goes back to normal (no stuck hand), the window is opaque again.
- [ ] **A-02** While dragging, move over the tab strip of the main window → the window becomes more
      transparent, a blue marker shows between two tabs; releasing there puts the tab at the marker.
- [ ] **A-03** Press **Esc** in the middle of a drag → the tab goes back to its place and the new
      window disappears. Releasing the button afterwards does nothing.
- [ ] **A-04** Do the same with the only tab of a detached window → the window jumps back to where
      it was when the drag began.
- [ ] **A-05** Release a dragged window with the pointer at the far **left** edge of the screen, then
      at the far **right** edge → it fills that half of the screen (never smaller than its minimum width).
- [ ] **A-06** Two monitors: drop a window on the other monitor → it stays there; its title bar is
      never above the top of the screen.
- [ ] **A-07** Drop a tab onto a window that overlaps another one → the window that is on top gets it.
- [ ] **A-08** The new window does not steal focus while you drag (the original window keeps
      receiving the mouse until you release); afterwards it becomes the active window.

### macOS menus and shortcuts

- [ ] **A-10** Click a detached window → the menu bar shows File / Tools / Window / Help (not just the
      application menu).
- [ ] **A-11** In a detached window: **Cmd+O**, **Cmd+S**, **Cmd+W**, **Cmd+N** (File → New) → each acts
      on that window's document, not on the main window's.
- [ ] **A-12** With a detached window active, **Preferences** and **Quit** in the application menu work.
- [ ] **A-13** File dialogs and message boxes opened from a detached window appear over that window
      (not behind the main window, and not as a sheet on the wrong window).

### Trackpad, pinch, mouse

- [ ] **A-20** Two-finger scroll on a workflow canvas → it moves, the content follows your fingers;
      no zoom.
- [ ] **A-21** Pinch → zooms around the pointer, within limits (it stops zooming out and in).
- [ ] **A-22** Cmd+scroll (or Ctrl+scroll) → zooms around the pointer.
- [ ] **A-23** Two-finger double tap (smart zoom) → fits the whole workflow in the window.
- [ ] **A-24** A classic mouse wheel (not a trackpad) → zooms, as before.
- [ ] **A-25** Magic Mouse / other precise-scroll devices pan and zoom sensibly.

### File watching

- [ ] **A-30** Expand a folder in the side panel. From Finder or a terminal create, rename and delete a
      `.cwl` file in it → within about a second the list updates; the expanded folders, the selection
      and the scroll position stay.
- [ ] **A-31** Copy 50+ files into an expanded folder at once → one refresh, no flicker, no freeze.
- [ ] **A-32** A folder on a network share or a cloud-synced folder as a workspace folder → no error
      dialog, no freeze (the number of watched folders is limited).

### Screen

- [ ] **A-40** Retina and non-Retina monitors: the halos on compared steps, the underline of a step
      name on hover, the blue marker on the tab bar and the new icons (eye, target, link, arrows,
      exchange) are crisp and in the right colour.
- [ ] **A-41** Full-screen mode, Spaces, a minimised window: **Window → Tile Windows Side by Side** and the
      Window menu entries still bring the right window forward.

---

## B. Detached windows, reattaching and workspaces

Set-up: open `echo.cwl`, `uppercase.cwl`, `01-hello-world.cwl` in the main window.

- [ ] **B-01** Right-click a document tab → **Move to New Window** → a window with the side panel on the
      left, its own menu bar, tabs and status bar.
- [ ] **B-02** The side panel of the new window shows the same folders as the main window; the folder of
      the document is the current one (see the status bar).
- [ ] **B-03** Right-click a tab in the new window → **Move to Main Window** (or the name of another
      window) → the tab moves; the empty window closes.
- [ ] **B-04** The button at the right end of a detached window's tab bar → all its tabs go back to the main window.
- [ ] **B-05** **Window → Reattach All Tabs to the Main Window** (appears only while a window is detached).
- [ ] **B-06** The **Welcome** tab cannot be dragged out, but can be reordered.
- [ ] **B-07** A plain click on a tab, or reordering tabs by dragging inside the bar, never detaches anything.
- [ ] **B-08** The only tab of a detached window cannot be torn off again: dragging it moves the window.
- [ ] **B-09** A window with two tabs: drag one out → a third window, whose workspace is a copy of the
      window it came from.

### Workspaces are separate and merge

- [ ] **B-20** In a detached window add a folder (**+ Add a Folder**). The main window's workspace does not
      change; quit and restart: the folder is not remembered by the main workspace.
- [ ] **B-21** Drag a tab from that window back to the main window → the added folder now appears in the main
      workspace (and is remembered after a restart).
- [ ] **B-22** Drag a tab from the main window onto a detached window's tab bar → the detached window gets the
      main window's folders too (merge works in both directions).
- [ ] **B-23** Removing a folder in a detached window does not remove it from the main workspace.
- [ ] **B-24** A folder that contains another workspace folder replaces it when merged (nested folders).

### Documents in several windows

- [ ] **B-30** Open a file from the side panel of a detached window → it opens in that window.
- [ ] **B-31** Open a file that is already open in another window → that tab (and window) comes to the front;
      nothing is opened twice.
- [ ] **B-32** **File → New → Workflow** in a detached window → the new document opens there.
- [ ] **B-33** The **Window** menu lists all documents of all windows; choosing one raises its window and tab.
- [ ] **B-34** Save, Save As, Reload, Validate, Upgrade version (File and Tools menus) act on the document of
      the window you use them in.
- [ ] **B-35** Double-clicking a step in a workflow in a detached window opens the step inspector there;
      dialogs (Input, Output) open next to that window.
- [ ] **B-36** The **Summary** tab: opening a step from it opens in the same window as the workflow.
- [ ] **B-37** In a detached window whose workspace has a different current folder than the main window's: **File → Save As**, **File → Open file…** and the document toolbar's save for an
      unsaved document start in **that window's** current folder (status bar), and the Git buttons use the folder of that window's workspace when the document has no file yet.

### Closing

- [ ] **B-40** Close a detached window that has a document with unsaved changes → "Save changes?"; **Cancel**
      keeps the window and the document.
- [ ] **B-41** Close the last tab of a detached window → the window closes by itself.
- [ ] **B-42** Quit (Cmd+Q) with detached windows open and unsaved changes in one → prompts; **Cancel** aborts the quit
      and the windows remain.
- [ ] **B-43** Close the main window while detached windows are open → everything closes (with the prompts).

### Snapping and tiling

- [ ] **B-50** **Window → Tile Windows Side by Side** with the main window and one detached window → two
      columns across the screen, the main window on the left.
- [ ] **B-51** The same with three windows → three columns; if the windows cannot be that narrow they
      overlap like a staircase but stay on the screen.
- [ ] **B-52** Resize a window narrower: the Info tab ribbon (format/created/modified) and the Code tab's "File URI"
      row clip instead of forcing the window to stay wide; the status bar path does not force the width either.

---

## C. Session restore

- [ ] **C-01** Open several documents in the main window and in two detached windows (different positions
      and sizes), quit, start again → the same windows, tabs, positions and sizes; the tab that was shown is shown.
- [ ] **C-02** The main window opens at the size set in the Configuration dialog (its position/size is not restored).
- [ ] **C-03** A document that was never saved is not restored (you were asked to save it when quitting).
- [ ] **C-04** Rename or delete a file between two sessions → it is skipped, no error dialog; a window whose
      files are all gone is not created.
- [ ] **C-05** Quit with a window on a second monitor, start without that monitor → the window appears on the screen.
- [ ] **C-06** The detached window's own workspace folders come back with it (not the main window's).
- [ ] **C-07** **Tools → Configuration → General**: untick *Reopen the documents and windows of the last
      session at start* → the next start is clean, and the old session is forgotten.
- [ ] **C-08** Opening the restored documents does not change the **Recent** list order.
- [ ] **C-09** `uv run ./cwled.py --input-file tests/echo.cwl` with a saved session → the file opens in
      addition to the restored tabs and is the tab shown.
- [ ] **C-10** Restoring a session with ~10 documents: the application starts in a reasonable time.
- [ ] **C-11** An **existing** configuration file that has none of the new keys (`restore_session`, `session`, `workspace_show_hidden`, `workspace_follow_document`) → the application starts,
      restore is on, the eye button is off and the follow button is on; after quitting the keys are written without disturbing the rest of the file.
- [ ] **C-12** **Tools → Reset configuration to default** (then restart) → the defaults of `resources/config/cwled.yaml` apply, including the four new keys.

---

## D. Workflow graph: clicking names, opening steps

Set-up: open `50-workflow.cwl` (Visual Editor tab).

- [ ] **D-01** Click the **name** of the step `echo` (the label under the circle) → the left panel shows the
      Workspace page with `echo.cwl` selected and its folders expanded.
- [ ] **D-02** The same while the **Recent** page of the side panel is shown → it switches to Workspace.
- [ ] **D-03** Click the **circle** of a step → the step is selected (teal ring, the rest fades); the panel does not change.
- [ ] **D-04** Drag a step by its **name** → the step moves; the panel does not change.
- [ ] **D-05** Pointing at a step's name underlines it and shows "Show echo.cwl in the workspace"; pointing at the circle does not.
- [ ] **D-06** Click the name of a workflow input or output → nothing happens.
- [ ] **D-07** Type something in the panel's search box (press Enter), then click a step name → the search is cleared and the file is selected.
- [ ] **D-08** A step whose file is outside every workspace folder → the status bar says so; nothing selected.
- [ ] **D-09** A step whose tool is in a hidden folder (`.steps`, after *Repackage workflow*) → the file is shown and the
      eye button of the panel turns on by itself.
- [ ] **D-10** Clicking a name does **not** change the folder where new files are saved (status bar, **File → Save As** start folder).
- [ ] **D-11** In a detached window the file is revealed in **that window's** panel, not the main window's.
- [ ] **D-12** **Cmd/Ctrl+click** the name of `echo` → `echo.cwl` opens in a tab of the same window; again → that tab comes to the front, no duplicate.
- [ ] **D-13** Open `51-workflow.cwl` (steps defined inside) → plain click on a step name selects the workflow's own file; **Cmd/Ctrl+click** →
      the **Code** tab opens with that step's definition selected.
- [ ] **D-14** **Double-click** a step's circle, then another step's name → the right panel (step inspector) opens each time;
      its × (or Esc) closes it; the panel is hidden until a step is double-clicked.
- [ ] **D-15** A workflow input node: double-click opens the Input dialog as before.
- [ ] **D-16** The Visual Editor of a workflow has **no** strip above the canvas (no Add Step / Duplicate Step buttons, no colour legend, no "Drop CWL files here" box); the canvas starts right under the document's tab bar
      and fills the editor, also in a detached window and at a small window size.
- [ ] **D-17** Drag a tool or workflow from the side panel (Workspace and Recent) and from Finder onto the canvas → it becomes a step where it was dropped; dropping several files adds them in a staircase;
      dropping something that is not a CWL file is refused; a workflow dropped on itself gives "A workflow cannot be a step of itself."
- [ ] **D-18** There is no Duplicate Step button any more (expected; the method `onDuplicateStep` is kept in `TabWorkflowEditor.py` without an interface). Note anything you miss now that it is gone.

---

## E. Moving around the canvas

Set-up: `60-test-record-wflow.cwl` or `50-workflow.cwl`, zoomed in.

- [ ] **E-01** Drag on an **empty** part of the canvas with the left button → the view moves (hand cursor); the nodes do not move relative to each other.
- [ ] **E-02** Drag a node → the node moves, not the canvas.
- [ ] **E-03** Drag from a port → a connection is drawn as before; dropping on empty canvas creates an input/output node.
- [ ] **E-04** **Shift+drag** on empty canvas → a selection rectangle; the nodes inside are selected; **Shift+click** adds to the selection.
- [ ] **E-05** A plain **click** on empty canvas → the selection is cleared and the view does not move.
- [ ] **E-06** Hold **Space** and drag from a node → the canvas moves and the node stays; the cursor is an open/closed hand; releasing Space restores it.
- [ ] **E-07** **Alt+drag** and the **middle button** drag still move the canvas.
- [ ] **E-08** Click the canvas, then **arrow keys** → it moves; **Shift+arrow** four times as far.
- [ ] **E-09** **+** and **-** zoom; **0** fits the whole workflow. (Click the canvas first so it has the keyboard focus.)
- [ ] **E-10** The zoom buttons (+, -, fit), still work; zoom stops at both ends; labels grow when zoomed out.
- [ ] **E-11** Delete / Backspace still delete the selected nodes; typing in a text field elsewhere does not move the canvas.
- [ ] **E-12** No stuck hand cursor after any of the above, including after dragging outside the window.

## F. Linked views

Set-up: `50-workflow.cwl` in one window and `51-workflow.cwl` (or `v2.cwl`) in another (detach one), both showing the Visual Editor.

- [ ] **F-01** **Window → Link Workflow Views** → pan one graph → the other pans by the same distance on the screen.
- [ ] **F-02** Zoom one (wheel, pinch, + / - keys, zoom buttons) → the other zooms by the same factor around the same screen point.
- [ ] **F-03** The link button next to the zoom buttons of the canvas and the menu entry show the same state, in both windows.
- [ ] **F-04** Turn it off → moving one no longer moves the other.
- [ ] **F-05** **Fit** (compress button / key 0) and moving nodes are **not** linked.
- [ ] **F-06** Two workflows with different zoom levels stay offset by the same on-screen distances when linked.
- [ ] **F-07** A workflow on a tab that is not shown is not affected; showing it again works normally (it just may be out of sync).
- [ ] **F-08** Closing a window or a document while linked causes no error.

---

## G. Workspace side panel

- [ ] **G-01** The search field is wide enough to type in at the default panel width; the sort and rescan buttons are next to it.
- [ ] **G-02** The eye button (below the search field, right side) shows/hides folders starting with a dot; `.git`, `node_modules`, `__pycache__`
      and virtual environments never show.
- [ ] **G-03** The target button (follow the open document) is on by default: switch tabs → the file of the shown document is selected and scrolled into view.
- [ ] **G-04** Follow does not act while the **Recent** page is shown, while a search is active, or for a document in a hidden folder while hidden folders
      are not shown (it never turns the eye button on by itself; clicking a step name does, see **D-09**).
- [ ] **G-05** Select another file in the tree, then type in the document → the selection is not taken back; switching tabs does move it.
- [ ] **G-06** Turn follow off → tabs are not followed; on → the shown document is selected at once.
- [ ] **G-07** Both settings are remembered after a restart.
- [ ] **G-08** Selecting files by following does not change the current workspace folder (status bar) nor the working directory.
- [ ] **G-09** The date of modification and the CWL class icon of a file update after you change its class (**Rescan**, or save).
- [ ] **G-10** **Speed:** your biggest real workspace: expanding folders, **Rescan** and search feel instant (the old code took seconds when
      many folders were open).
- [ ] **G-11** A workspace on a slow disk or network share is usable.
- [ ] **G-12** Folders that contain no `.cwl`, `.yaml` or `.json` file are not listed; `.yml` is not listed (known).

---

## H. Comparing documents

Set-up: the scratch workspace with the git commit, `50-workflow.cwl` and `v2.cwl`.

### Starting a comparison

- [ ] **H-01** Right-click a document tab → **Compare with…** → a list: the other open documents, **The saved version of this document**,
      **Git: <sha> <message>** entries (up to 8), **A file…**.
- [ ] **H-02** **Tools → Compare with…** does the same for the active document; without an open document it says so.
- [ ] **H-03** Outside a git repository there are no Git entries and no error.
- [ ] **H-04** Cancel at any point does nothing.
- [ ] **H-05** **A file…** with a file that is not valid CWL → a clear message, no crash, no new tab.

### The comparison tab

- [ ] **H-10** Compare `50-workflow.cwl` (left) with `v2.cwl` (right) → a new tab "50-workflow.cwl ↔ v2.cwl"; the left list names the changed
      parts (`inputs extra`, `steps uppercase`) and nothing else (no `id`, no `cwlVersion`, no file path noise).
- [ ] **H-11** Lines that differ are coloured: green only on the right, red only on the left, amber changed; gaps face lines that have no counterpart.
- [ ] **H-12** Scrolling one pane scrolls the other (vertical and horizontal).
- [ ] **H-13** The up/down arrow buttons go to the previous/next difference, wrapping around; clicking an entry of the list jumps to it.
- [ ] **H-14** The summary says "N differences · M parts changed · time"; for identical documents "The documents are the same" and the list says "No changes".
- [ ] **H-15** **Swap the sides** exchanges them; **Compare again** reads documents and files again.
- [ ] **H-16** Compare a document with **The saved version** after changing it without saving → the change appears; change it more, **Compare again** → updated.
- [ ] **H-17** Compare with a **git revision** after committing a change → only that change is listed.
- [ ] **H-18** Two tools (not workflows) and a JSON-format file compare correctly; no graph marks are attempted.
- [ ] **H-19** A big workflow (`60-test-record-wflow.cwl`) compares quickly and scrolls smoothly.

### Marks in the graphs

- [ ] **H-30** With **Mark the steps in the graphs** ticked: a halo around changed steps (amber), added (green), removed (red, dashed) in the graphs of the open documents.
- [ ] **H-31** Untick it → the marks disappear; tick it → they come back; close the comparison tab → they disappear.
- [ ] **H-32** The marks stay after the graph is redrawn (auto-arrange, edit a step, reload).
- [ ] **H-33** Only the document that is open gets marks when the other side is a file or a git revision.

### As a tab

- [ ] **H-40** Tear the comparison tab off into a window next to the workflows it compares; reattach it; both work.
- [ ] **H-41** Closing the comparison tab (× or File → Close tab) leaves the documents untouched.
- [ ] **H-42** Quit with a comparison tab open and restart → it is not restored (documents are).
- [ ] **H-43** Compare in a detached window; close that window → no error.

---

## I. Command line

- [ ] **I-01** `uv run ./cwled.py --input-file tests/echo.cwl --workspace tests` → the file opens in a tab.
- [ ] **I-02** `--workspace <empty new folder>` → the folder is created and shown in the side panel.
- [ ] **I-03** A relative `--input-file` path and a path outside the workspace → handled as before (error logged for the latter).

(The `--new-workflow`, `--new-commandline` and `--new-expression` options are in section **M**.)

---

## K. Composer look and feel

From the session that built the Composer-style redesign (theme, side panel, tabs, graph, step inspector, tool
inspector, expression editor). It was verified only headless with fallback fonts; nothing was tried on a real display.
The `docs/*.png` screenshots were generated the same way, so their fonts may differ from the real application.

### K-1. Real display / macOS only 🖥

- [ ] **K-01** Launch on a Retina Mac → the Composer dark palette everywhere, Montserrat upper-case section titles,
      Font Awesome icons crisp (not blurry), no white or light Fusion leftovers.
- [ ] **K-02** Open a tool, look at the Code tab and the bottom command-line preview → monospace font at a readable size,
      idle_fingers colours; the same font in the Expression Editor.
- [ ] **K-03** The macOS menu bar → File / Tools / Window / Help are in the system bar, Quit in the application menu (Cmd+Q);
      **Cmd+W** closes the current document tab and asks to save if it has unsaved changes.
- [ ] **K-04** Hover graph ports and edges and the info icons of the inspector → dark styled tooltips; rich text (bold headings) renders.
- [ ] **K-05** Drag a tool or workflow with the real mouse from the Workspace tree, from **Recent** and from Finder onto a workflow
      canvas → it becomes a step where it is dropped (a workflow adds *SubworkflowFeatureRequirement*).
- [ ] **K-06** Trackpad pinch / scroll zoom on the canvas → limited to 0.2–2×; node labels stay readable when zoomed out.
      (The trackpad scroll now *pans*; see **A-20** to **A-25**.)

### K-2. Workspace, tabs, welcome page

- [ ] **K-10** **+ Add a Folder** and **File → Add Folder to Workspace…** with the real folder picker, then restart → the new root is shown and remembered;
      right-click a root → **Remove from Workspace** removes it, files are untouched.
- [ ] **K-11** Welcome tab: click each **Actions** card, double-click an entry of **Recently Opened**, press the **+** tab button →
      a new document / the file / the Welcome tab opens.
- [ ] **K-12** Open a workflow → it lands on the **Visual Editor** (not Summary).
- [ ] **K-13** Open an unchanged tool → its tab is **not** marked `*`; edit something → `*` appears; save → it goes away.

### K-3. Workflow graph

- [ ] **K-20** Look at a workflow → circular nodes with a grey ring (teal steps, purple conditional steps, grey inputs and outputs, a file
      icon for File inputs), the label under each node, port names on hover, grey edges; hovering an edge shows "a → b".
- [ ] **K-21** Click a node → teal ring, unconnected nodes and edges fade; click empty canvas → restored; click an edge, then Delete → the edge is removed.
- [ ] **K-22** The canvas buttons bottom right: delete, zoom in/out, fit, auto-arrange, export (the real save dialog, SVG / PNG / JPEG) → each works,
      the exported image looks like the canvas. (There is now also a *link* button, see **F-03**.)
- [ ] **K-23** Drag from a step's output port to empty canvas → a new workflow output; from a visible input port → a new workflow input.
- [ ] **K-24** Switch to the Code tab and back → the graph keeps its zoom and node positions.

### K-4. Step inspector (the right panel)

- [ ] **K-30** Double-click a step → the panel opens on the right (no modal dialog); the header is the step's label or id; the tabs are
      **App Info / Inputs / Step** with **Inputs** selected; × or Esc closes it; double-clicking another step switches to it; deleting the step closes it.
- [ ] **K-31** **Inputs** tab: click a "default ▾" button with the real mouse → a popup menu (Default / Exposed / Port, with descriptions) appears next to it.
      **Port** → the port shows on the canvas and a "This port is not connected" warning; **Exposed** → a hidden workflow input, the Code tab shows
      `sbg:exposed: true` and `$namespaces` with `sbg`; **Default** again → that input is removed.
- [ ] **K-32** An optional File input: the Show/Hide switch → the port appears / disappears on the node.
- [ ] **K-33** Edit defaults (enum drop-down, number, text, Yes/No switch, array "New …" and trash, record fields) → the Code tab shows them as `default:` under
      the step's `in`; inputs you did not touch stay unchanged.
- [ ] **K-34** **Step** tab: rename the ID to an existing one → a red message under the field; a valid rename → connections still work and **Tools → Validate** passes.
- [ ] **K-35** **Step** tab: Label → the node title; Scatter and Scatter Method; **When** through the `</>` Expression Editor → the node turns purple; Description;
      **Set Hints** (add / edit / delete) → all saved and the file validates.

### K-5. Tool editor

- [ ] **K-40** Click an argument, input or output row → the right inspector opens and changes apply live (the Code tab and the bottom preview update).
- [ ] **K-41** Bottom command-line preview: sample values are shown; hover a part → highlight and tooltip; click it → that entry opens in the inspector;
      set a **Test Value** on an input → the preview uses it.
- [ ] **K-42** The `</>` button attached inside fields → the Expression Editor opens, evaluates **without Node.js installed**, completes after `inputs.` and on Ctrl+Space,
      an infinite loop stops after 3 s; a broken expression shows a red × in the field with the error as tooltip.
- [ ] **K-43** The **Requirements** section → elements stacked vertically; the **Other** section → stdin / stdout / stderr redirects and exit codes are editable.

### K-6. Dialogs and input editors

The row editors of the tool's Input / Argument / Output lists are built from the old modal dialogs (`DialogInput.py`, `DialogOutput.py`, `DialogArgument.py`, `JavascriptEditor.py`) and shown in the right-hand inspector.

- [ ] **K-50** Open a tool with many kinds of inputs and outputs (`05-input.cwl`, `06-array-inputs.cwl`, `07-record.cwl`, `09-arguments.cwl`, `12-stdout.cwl`), click **every** argument, input and output row and close it
      again **without editing** → the tab does **not** get `*` and the Code tab text is unchanged. Optional stays optional; `shellQuote: false`, `separate`, `itemSeparator`, position 0, stdout/stderr
      output types and record names are kept.
- [ ] **K-51** Change an input's type in the inspector (string → enum → record → File) → no crash, the form rearranges, the Code tab follows.
- [ ] **K-52** 🖥 On a workflow canvas, double-click a workflow **input** or **output** node → the modal InputDialog / OutputDialog in the dark theme, with `</>` buttons attached inside fields; **OK** applies,
      **Cancel** changes nothing.
- [ ] **K-53** Press `</>` in an environment variable value, an InitialWorkDir entry, a default value and a requirement expression field → the Expression Editor opens, and closing it never quits the application
      (the env var `</>` used to exit the application).

### K-7. Requirements and section widgets

- [ ] **K-60** Tool Visual Editor → **Requirements**: elements are stacked one below the other; edit the resource requirement (cores / RAM) twice → the Code tab shows **one** ResourceRequirement, not two.
- [ ] **K-61** **Docker image**, **Env vars**, **InitialWorkDir**, **Secondary Files**: add a row, edit it, delete it with the trash icon → the list and the Code tab update; an empty list shows Composer's blank state
      with a blue "Add …" button. After this check the application starts and the InitialWorkDir section works (the old, unused `cwled/InitialWorkDir.py` was deleted).
- [ ] **K-62** 🖥 Hover the small icon buttons (trash, edit, `</>`, "+ Add" links) → the icon lightens, the cursor is a pointing hand.
- [ ] **K-63** 🖥 Toggle switches (Required, Separate value and prefix, shellQuote …) → a blue/grey Composer switch with Yes/No text; clicking the text also toggles.
- [ ] **K-64** **Tools → Validate** on a broken document → an error dialog readable in the dark theme (red/green title, dark details box).
- [ ] **K-65** App Info **keywords / tags**: add and remove tags → blue pills with a white ×; removing works.

### K-8. Tabs and small windows

- [ ] **K-70** **App Info** tab: the bottom file-info ribbon is dark with muted text; the AI (magic wand) button is blue; exit codes are **not** in App Info any more (they moved to the Visual Editor's *Other* section).
- [ ] **K-71** **Code** tab: dark idle_fingers colours, a readable line-number margin, the file path label coloured (orange scheme, blue folder, red file name). Only colours and fonts changed: the YAML/JSON toggle,
      find/replace and jump-to-field work as before (try them).
- [ ] **K-72** **Tools → Generate template** → the template is shown in the dark code style and is readable.
- [ ] **K-73** **Tools → Configuration** → a dark dialog; the *Paths* tab's "Workspace" field has a tooltip saying it is the first workspace folder.
- [ ] **K-74** The **Input Ports / Output Ports** lists: the *Type* column reads `File`, `Array<File>`, `string?` for optional, `File, Array<File>` for unions, `record` / `enum`; the *Binding* column shows the prefix, else
      `pos: N`, `pos: 0` for a binding without a position, `unbound` without `inputBinding`.

### K-9. Multi-folder workspace

(Also see **R-04**, **R-05**, **B-20** to **B-24** and **K-10**.)

- [ ] **K-80** 🖥 Add a folder that is already in the workspace → "already in the workspace"; add a sub-folder of a root → "already in the workspace, inside X"; add a parent of existing roots → it replaces them.
- [ ] **K-81** Open a document from folder 2, then remove folder 2 from the workspace → a confirmation warning first ("files outside the workspace cannot be saved"); the document stays open.
- [ ] **K-82** **Save As** to a path outside every workspace folder (for example the Desktop) → refused with "Cannot save … outside of the workspace folders … Add its folder to the workspace first."
- [ ] **K-83** Start with `--workspace /some/folder` → that folder is first for this session only (it is **not** written to the configuration). An old configuration with only `workspace:` shows that folder as the first
      root. The configuration file (`~/Library/Application Support/cwled/cwled.yaml` on macOS) gets `workspace_folders` only after you add or remove a folder, and `workspace` is then the first folder.
- [ ] **K-84** Git: make folder 1 and folder 2 separate git repositories, add both to the workspace, open a file from folder 2 and use the git actions of the document toolbar (code-fork icon) → the commit/tag lands in
      **folder 2's** repository (check `git log` there), not folder 1's. If folder 2 is not a repository and CWLed offers to create one, it must be created in folder 2. Push and pull were **never tested**.

### K-10. Known gaps and what not to test (do not report as bugs)

- Steps show only the ports of required File/Directory inputs and of connected inputs (Composer's behaviour); use the step inspector's Port / Show to connect any other input.
- Workflow input and output nodes still open the modal Input / Output dialogs; only steps use the side panel. There is no toolbar above the workflow canvas any more (Add Step, Duplicate Step, the colour legend and the "Drop CWL files here" area were removed); steps are added by dropping files on the canvas.
- *Pick Value* appears only for inputs with several connections; *Set Hints* edits only class/value hints (others are read-only) and opens as a normal OS window.
- Not done yet, compared with Composer: tree carets and the blue strip on the selected row, search only on Enter, tab widths follow the titles, `*` instead of
  italics for unsaved tabs, no side-panel toggle in the status bar, no Close Others / Close All tab menu, long names clipped in the tree, `.yml` files not listed.
- One crash at application shutdown happened once in an automated run and never reproduced (0 of 8 reruns). If you see a crash on quit, note it.
- `DialogStep.py` (the StepDialog) is only a fallback for a graph that has no step inspector; it is not reachable from the normal interface, so do not test it.
- The **Summary** tab and `docs/FLOW.md` (developer documentation) were not changed in behaviour; nothing to test there beyond **B-36** and **N-02**.
- The *Pick Value* source-order list (`qSortedList.py`) appears only in the step inspector for a CWL 1.2 input that has several connections and `pickValue` set: low priority.

---

## L. Error dialogs (thread safety of the error log handler)

From the session that fixed the crash of the error-dialog log handler (`cwled/logger.py`): the dialog is now always built and shown on the GUI thread, wherever the
error was logged. CWLed's own code has no worker thread that logs an error; only watchdog's internal threads do (logger name `fsevents`, and only when FSEvents
fails), which cannot be triggered on demand, so the worker-thread checks start the application with the command below. Run it from the repository root.
The automated tests remove this handler (so a logged error never opens a dialog in a test): **nothing here is covered by `uv run pytest`.**

The command logs five identical ERRORs from a plain `threading.Thread` three seconds after the main window opens:

```bash
cd cwled && ../.venv/bin/python -c "import logging, threading, main, MainWindow as M; from PyQt6.QtCore import QTimer; show = M.MainWindow.show; M.MainWindow.show = lambda self: (show(self), QTimer.singleShot(3000, lambda: threading.Thread(target=lambda: [logging.getLogger('manual-test').error('worker-thread test error') for _ in range(5)]).start())); main.main()"
```

For the "two different errors" variant, replace
`[logging.getLogger('manual-test').error('worker-thread test error') for _ in range(5)]` with
`[logging.getLogger('manual-test').error(m) for m in ('error A', 'error B', 'error A')]`.

- [ ] **L-01** Run the worker-thread command and wait 3 s → **exactly one** dialog titled "Error from manual-test" appears and the application does not crash (before the fix it died
      with SIGTRAP, exit code 133). All five identical log lines print in the terminal at once, before you click OK: the worker thread was not blocked.
- [ ] **L-02** Click OK → the dialog closes normally, no second copy of the same error appears, the main window responds again.
- [ ] **L-03** Keep using the application: create a new CommandLineTool and a new Workflow, switch between their tabs, trigger a message box (see **L-05**) → everything works.
      (Before the fix the crash came later, in unrelated calls such as `QTabWidget.setCurrentWidget` or `QMessageBox.setIcon`.)
- [ ] **L-04** Run the "two different errors" variant → two dialogs: "error A" with "error B" stacked on top (the second "error A" is dropped because A is still open).
      Close B, then A → both close normally and no third dialog appears.
- [ ] **L-05** A GUI-thread error, behaviour unchanged: open a `.cwl` file, close its tab (it stays in **File → Recent**), rename or delete the file in Finder, then pick it from
      **File → Recent** → **first** an "Error from MainWindow" dialog ("Recent file … no longer exists"); the "File Not Found" message box appears only after you click OK.
- [ ] **L-06** A GUI-thread error at startup: `cd cwled && ../.venv/bin/python main.py does-not-exist.cwl` → one "Error from MainWindow" dialog ("does not exist" or
      "outside the workspace folders"); OK closes it and the main window opens.
- [ ] **L-07** Normal macOS with FSEvents working: open a `.cwl` file and edit it in another editor → no error dialog; the usual reload prompt appears (file watching is not affected).
- [ ] **L-08** FSEvents unavailable (only where the original crash happened, e.g. a restricted environment): open a file → one dialog "Error from fsevents" with
      "Unhandled exception in FSEventsEmitter" and a traceback; OK → the application keeps running.
- [ ] **L-09** Quit after these tests → it exits normally with no macOS crash report.

Expected behaviour, not bugs:
- Identical errors are merged only while their dialog is open; the same error logged again after you click OK opens a new dialog.
- Different errors still stack modal dialogs, by design.
- A worker-thread error dialog appears a moment after the error, when the event loop gets to it; GUI-thread errors still block until OK, as before.
- When FSEvents is unavailable you still get the error dialog (without the crash), and changes made by other programs are not detected for those files
  (the reload prompt does not appear): there is no `PollingObserver` fallback yet.
- The dialog has no parent window (as before), so macOS may centre it on the screen instead of over the active CWLed window.

Not verified by that session: the dialogs were closed automatically after about 150 ms, so their appearance, position, focus and closing by mouse or keyboard were never looked at;
the real FSEvents failure was never reproduced (it was simulated by logging the same message from a thread); only macOS from source, not Linux, Windows or the PyInstaller `.app`.

---

## M. Command line: `--new-workflow`, `--new-commandline`, `--new-expression`

From the session that fixed the crash of these options (they used the removed `cwl_dict`; now `nameNewDocument()` in `cwled/main.py` sets the id of the new
document). Run from the repository root. Verified headless only (by that session and by `pytests/test_command_line.py`); there was no real display, no real
Save As dialog and no packaged build.

- [ ] **M-01** `uv run ./cwled.py --workspace tests --new-workflow MyFlow` → one document tab titled exactly `MyFlow` (no leading `*`, not `Workflow_xxxx`);
      the window title reads `MyFlow: <unsaved> (v1.2)`, the Window menu entry `Workflow: MyFlow`, the App Info tab's ID field shows `MyFlow`.
      Repeat with `--new-commandline MyTool` (class CommandLineTool) and `--new-expression MyExpr` (class ExpressionTool).
- [ ] **M-02** Open the **Code** tab of that document → it shows `id: MyFlow` and the matching `class:` (YAML and JSON).
- [ ] **M-03** Close the tab, or quit, without touching anything → **no** "unsaved changes" prompt. Relaunch and change the Label or Description in the Info tab →
      the tab gets `*` (it shows `*<label>`, because the tab title prefers the label to the id).
- [ ] **M-04** **File → Save As** on the named unsaved document → the suggested file name is based on the id (`MyFlow.cwl`); after saving the tab shows the file name,
      the window title the saved path and the file on disk still contains `id: MyFlow` (not turned into a URI, not stripped). Reopen it with `--input-file` and check the tab and ID.
- [ ] **M-05** Empty name: `--new-workflow ""` → no document is created and the application starts normally (the option is tested for truthiness, so the empty string
      is ignored). `--new-workflow` with no value at all → an argparse error message, not a crash.
- [ ] **M-06** Names with spaces and special characters: `"My Flow"`, `"a/b"`, `"a#b"`, `"é ü 日本"` → the name is stored verbatim as the CWL id. The tab for
      `a/b` and `a#b` shows only the last part (`b`). Check the Save As suggestion for `a/b` (no path separator in the file name) and run **Tools → Validate**
      to see whether ids with spaces are accepted. The name is not sanitised.
- [ ] **M-07** Combine with `--workspace tests` (relative) and `--workspace /some/path` → both resolve. A workspace folder that does not exist is **created**
      (a typo leaves an empty folder behind; this was always so).
- [ ] **M-08** `--input-file tests/01-hello-world.cwl --new-workflow MyFlow` → the file opens as a tab **and** the `MyFlow` tab is added after it and is the one in front;
      neither tab shows `*`. (With a saved session: see **C-09**.)
- [ ] **M-09** `--new-workflow A --new-commandline B` → only `A` is created (the options are an if / elif chain, workflow before commandline before expression;
      the others are silently ignored).
- [ ] **M-10** Detach the named tab and reattach it → the title stays `MyFlow` without `*`.
- [ ] **M-11** The same command lines through the packaged application (build with `cwled.spec`): run its executable from a terminal with the same flags.
      The executable name and path are unverified.
- [ ] **M-12** Note for developers: `nameNewDocument()` calls the private `ChildWindow._mark_clean_snapshot()`; switch to a public method if one is added.

---

## N. Drawing the workflow graph while the pointer is on the canvas

From the session that fixed the node-search popup. Before the fix, `CWLGraph.showGraph()` called `toggle_node_search()`, which opened a modal "tab search" menu at the
pointer whenever a graph was drawn while the pointer rested on the canvas, and the application stayed blocked until the menu was dismissed. The fix removes that call (one
line in `cwled/NetworkGraph.py`) and adds a test.

> **Status when this list was written:** the fix is **not yet applied to this checkout**. It is a patch (one line removed from `cwled/NetworkGraph.py`, plus a test). The original patch from that session
> edits test files under `tests/`, but the test code now lives in `pytests/` (`tests/` holds only CWL documents), so use the path-corrected copy, which applies cleanly:
> `/private/tmp/claude-502/-Users-baners23-cwled/ada57df2-bd58-4dc9-ba7e-20af1388197c/scratchpad/node-search-popup-fix-pytests.patch`
> (from the repository root: `git apply -p1 <that file>`; the temporary directory may be cleaned, so apply it soon). The checks below only mean something once it is applied; without it, the popup can still appear.

What redraws the graph (so what can trigger the old problem): a tab switch back to the Visual Editor (every tab switch refreshes all tabs), a file **reload**, and the Summary
tab's own graph. Committing an edit in the inspector does **not** redraw it; panning and zooming never did.
There is **no** Tab-key node search in this application (pressing Tab on the canvas opened nothing before the fix either); the menu only ever appeared through that call,
so nothing a user could reach was lost.

- [ ] **N-01** Open a workflow, show the Visual Editor, leave the pointer resting on the canvas, switch to another tab and back **without moving the mouse** (keyboard tab shortcut,
      or click the tab and slide back) → the graph is redrawn, **no** search menu appears, the application stays responsive.
- [ ] **N-02** The same on the **Summary** tab (it has its own graph): pointer resting where its graph is, switch to it and back → no menu.
- [ ] **N-03** With the pointer resting on the canvas, reload the file (**File → Reload file**, or the toolbar button) and confirm the prompt with the keyboard (Return/Y),
      not the mouse → the graph is reloaded, no menu.
- [ ] **N-04** Edit the document in the Code tab (change a step id or add a step), switch back to the Visual Editor with the pointer on the canvas → the graph shows the edit, no menu.
- [ ] **N-05** 🖥 Change the open file in an external editor, return to CWLed with the pointer on the canvas, accept the reload prompt by keyboard → the graph updates, no menu.
      (Needs the real file watcher; it cannot be tested headless.)
- [ ] **N-06** Double-click a step so the inspector opens, edit the label or id with the keyboard while the pointer rests on the canvas, press Enter/Tab → no menu
      (this never redrew the graph; the redraw happens when you leave the tab).
- [ ] **N-07** Click an empty spot of the canvas and press **Tab** → nothing happens (there is no node search in this application; steps are added by dropping a document on the
      canvas). The **Auto-arrange** button (the canvas's own overlay control, the old "Reset Plot") still lays out the graph as before, with no menu.
- [ ] **N-08** With **Link Workflow Views** on and two workflow windows, pan and zoom in one while the pointer rests over the other → no menu.
- [ ] **N-09** A **comparison** (section **H**) between two open workflows: click **Compare again**, switch tabs and back with the pointer on a workflow canvas → no menu, the
      marks on the steps are still there. (Anything that goes through `ChildWindow.onUpdateCWL` redraws the graph; this combination was not exercised by that session.)
- [ ] **N-10** 🖥 Do one pass of N-01 to N-04 on real macOS, not offscreen. All the verification was done on Qt's offscreen platform; that the viewer counts as "under the mouse"
      right after a tab switch is generic Qt code, but it could not be confirmed on Cocoa, so this pass is the real confirmation.

Related quirks noticed there and **not fixed** (do not report them as new bugs):
- Every tab switch re-populates all tabs, including a full graph rebuild. Harmless now, but wasteful, and the reason a tab switch is a redraw trigger at all. It also means that a large
  workflow may feel slow when you switch tabs (see **R-11**).
- A document under the operating system's temporary directory is treated as temporary (see the note in *How to use this list*).

---

## O. Remote folders over SSH (EC2 instances)

Branch `ssh-remote-folders`. The automated tests copy and upload with a shell on the same machine (no network, no
`ssh`), so everything that needs a real instance is here. You need an EC2 instance (or any machine you can `ssh` to with
a key that needs no typing: `ssh-add` it first) and a folder on it with a few CWL documents, for example
`ssh my-ec2 'mkdir -p ~/cwl-test && cat > ~/cwl-test/hello.cwl' < tests/01-hello-world.cwl`.
Back up `~/.ssh/config` before editing it for these checks.

### The hosts

- [ ] **O-01** 🖥 **+ Add a Remote Folder (SSH)** in the side panel, right below **+ Add a Folder** → a dialog opens with the hosts of your `~/.ssh/config`; the text above the list says how many EC2 instances there are among how many hosts. The same dialog opens
      from **Add Remote Folder…** next to **Add Folder…** on the Welcome tab, from the context menu of an empty part of the Workspace tree, and from the button in the empty side panel (remove every workspace folder). There is **no** entry for it in the File menu (only **Sync Remote Folders**).
- [ ] **O-02** 🖥 The instances you know are EC2 machines are listed with their host name, user and **yes**; hovering a row shows the key, the jump host, the comment and *why* it counts as EC2
      (an `amazonaws.com` name, an instance id, a comment or name that says EC2/AWS...). A host that only has a `.pem` key says **probably**.
- [ ] **O-03** 🖥 Hosts that are not EC2 (a laptop, a university cluster) are **not** listed until **Show all hosts** is ticked; then they all are. The filter field narrows the list while typing (name, host name, user, comment).
- [ ] **O-04** 🖥 Edit `~/.ssh/config` (add an EC2 host with a comment line `# EC2 test` above its `Host` line), press **Reload** → the new host appears without closing the dialog. Put a host in a file that the config
      `Include`s (`Include config.d/*`) → it is listed too. A `Host *` block with a `User` or `IdentityFile` is applied to the hosts below it as `ssh` does (compare with `ssh -G <host>`).
- [ ] **O-05** 🖥 Move `~/.ssh/config` away for a moment → the dialog says there is no SSH configuration and names the path; typing `user@ec2-….compute.amazonaws.com` in **Another host** still works. An empty config, or one without EC2 hosts,
      says so and lists every host.
- [ ] **O-06** 🖥 **Test connection** on a host → "Connected to … Its home folder is /home/…" and the folder field is filled in. On a host that is down: the error text from `ssh` appears in red and the dialog stays usable.

### Choosing and adding a folder

- [ ] **O-07** 🖥 **Browse…** → the folders of the instance are listed (hidden ones too, files greyed); a double click goes into a folder, **Up** goes back, a path typed in the field + Return jumps there. **Click** a folder once (the button changes to
      **Choose “name”**) and press it → the field gets *that* folder, not the one you were looking into (e.g. highlight `pipeline-assets` while looking into `/home/you/work` → `/home/you/work/pipeline-assets`);
      with nothing highlighted the button says **Choose this folder** and takes the folder that is shown.
- [ ] **O-08** 🖥 **Add Folder** → the dialog shows "Reading …", then closes (quickly, whatever the size of the folder: only its first level is read). The Workspace panel gets a root named `my-ec2:/home/…/cwl-test` with a server icon; its tooltip shows the remote path and where the copy is on this computer. Under it are the
      documents of that folder and its sub-folders (no hidden folders, no `node_modules`, no notes or images, no document over 2 MB), also sub-folders that hold only other folders.
- [ ] **O-09** 🖥 Open a document of the remote root, edit it, **Save** → the status bar says "Uploading to …" and then "Saved on my-ec2:/…". Check on the instance (`ssh my-ec2 cat ~/cwl-test/hello.cwl`) that the new content is there, and that
      the file keeps its owner and mode (`ls -l`).
- [ ] **O-10** 🖥 **Save as…** a new name, inside a **new sub-folder** of the remote root → the file (and the folder) appear on the instance. **Save as** a name *outside* the remote root → nothing is uploaded.
- [ ] **O-11** 🖥 On the instance, change a file and add one (`echo … > ~/cwl-test/new.cwl`; also one in a sub-folder you opened and one in a sub-folder you never opened); in CWLed right-click the remote root → **Sync from Remote** → the status bar says how many
      files were copied, `new.cwl` and the new file of the opened sub-folder appear in the tree (the one of the never opened sub-folder appears when you open that folder), and an open
      document that changed asks whether to reload (as for any file changed by another program).
- [ ] **O-12** 🖥 **File → Sync Remote Folders** syncs every remote folder; without a remote folder it says that the workspace has none.

### When things go wrong

- [ ] **O-13** 🖥 Turn Wi-Fi off, edit a remote document and **Save** → a warning says the file was saved on this computer but could not be uploaded (with the `ssh` error) and the document is still marked saved locally.
      Turn Wi-Fi on, **Save** again → it is uploaded. Repeat the offline save, then **Sync from Remote** *before* saving again → your change is still in the file (it is newer than the remote one).
- [ ] **O-14** 🖥 Use a key with a passphrase that is **not** in the agent (`ssh-add -D` first) → the error says CWLed never asks for a password and that the key has to be added with `ssh-add`; after `ssh-add` it works.
- [ ] **O-15** 🖥 Use a host that is not in `~/.ssh/known_hosts` → the error tells you to connect once in a terminal to accept the host key; it does **not** accept it silently.
- [ ] **O-16** 🖥 A host that needs `ProxyJump` (bastion) or an `aws ssm` ProxyCommand works exactly as `ssh <host>` does in a terminal (if you have one of these).
- [ ] **O-17** A folder path that does not exist on the instance → "The folder … cannot be opened on …" in the dialog, nothing is added and no empty root appears.
- [ ] **O-18** The dialog while a copy is running: **Cancel** and the window close button do nothing until the copy ends (known limitation: there is no way to cancel it).

### Folders are read when they are opened

- [ ] **O-25** 🖥 Add a folder of the instance that has **many sub-folders and thousands of documents** (a real project, a pipelines repository) → it is added in a few seconds (it used to take as long as copying everything). Only its first level is
      on your disk afterwards (look in the data folder: the sub-folders are there, empty).
- [ ] **O-26** 🖥 Expand a sub-folder → a *Loading…* row shows under it, the status bar says "Reading host:/…/sub-folder …", then the documents and sub-folders appear and the status bar says how many were copied. Expanding it again, or collapsing and
      expanding, asks nothing more (the status bar stays quiet).
- [ ] **O-27** 🖥 Sub-folders are listed before you open them, whatever they hold; one that turns out to hold no document is empty when opened (it stays as an empty folder until you rescan or restart).
- [ ] **O-28** 🖥 Turn Wi-Fi off and expand a sub-folder you never opened → under it: "Could not be read: …" and the status bar says so (no dialog). Turn Wi-Fi on, collapse and expand it again → it is read.
- [ ] **O-29** 🖥 Quit and start CWLed again, without a network connection → the remote root and the sub-folders you opened before show what was copied, and documents can be opened and edited (saving cannot upload, see O-13). With the network back,
      expanding a sub-folder reads it again, once per session.
- [ ] **O-30** 🖥 With a workflow of the remote folder open, click the **name** of a step or switch tabs (the panel follows the open document) → the file is shown in the panel without any reading from the instance (the status bar shows no "Reading …").
- [ ] **O-31** The **search** of the panel finds documents of the folders you opened, not of the ones you never opened (known limitation: they are not on your computer yet).

### Opening a workflow: the tools it refers to

- [ ] **O-32** 🖥 Add a remote folder that is a repository of pipelines (workflows in `workflows/…`, tools in `tools/…`, the workflows referring to the tools with `run: ../../../tools/…`). Expand only `workflows/<name>/<version>` and **double-click the workflow** → the status bar
      says *Reading the N files that … refers to from host:/…*, the workflow opens **with its steps** (no "undefined reference to file:///…/tools/…" error, which is what this used to give), and `tools/…` now shows in the panel with the tools it uses.
- [ ] **O-33** Open the same workflow again after closing it → no "Reading…" message (the tools are here). Open a workflow that refers to a **sub-workflow** that refers to tools → all of them are copied (a few rounds), and it opens.
- [ ] **O-34** 🖥 On the instance rename one of the tools, open the workflow → a message says the workflow refers to files that do not exist in the remote folder (names them); the workflow opens anyway and its load error names the same file.
- [ ] **O-35** 🖥 Turn Wi-Fi off, open a workflow whose tools were never copied → a message says the files could not be read from the remote machine, with the `ssh` error; the workflow opens anyway. A workflow whose tools are already here opens without any message.
- [ ] **O-36** 🖥 Add as remote folder only `…/workflows` of a repository whose tools are in the sibling `tools/` folder, open a workflow → a message says it refers to files **outside** the remote folder (it lists some) and to add a parent folder; add the parent folder → it opens with its tools.
- [ ] **O-37** Tools, **Validate** and the other commands on a workflow opened this way work (they need the tools on disk); **Save** uploads only the workflow (and the status bar says so), the tools that were copied are not uploaded unless you change them.
- [ ] **O-38** 🖥 Open a remote workflow (the copies are kept in `~/Library/Application Support/…`, a folder with a space) and press **Save**: its `run:` paths are as they were (not `…/Application%20Support/…`), the steps show their tools, and the file on the instance still has `../../../tools/…`-style paths.
- [ ] **O-39** 🖥 Click the **Rescan** button (the circular arrow next to the search field) with a remote folder in the workspace → the status bar says "Syncing host:/… …" and then how many files were copied; a file you added or changed **on the instance** (also in a sub-folder you had opened) shows up / is replaced, a sub-folder you never opened is not read. Without any remote folder the button works as before and the network is not touched.
- [ ] **O-40** 🖥 On the instance **rename a folder** you have opened (and one at the first level, and a document) and click **Rescan** → the new names show (the folders empty until you open them, the document copied), and the **old names are gone**; documents that were in the old folders are gone from the copy too. The open tabs of such documents stay open.
- [ ] **O-41** 🖥 A folder of the instance that holds **no CWL document** (data, source code) is listed; open it → *No CWL documents* (or its sub-folders); **Rescan** does not make it disappear. Hidden folders (`.git`) and `node_modules` are still not listed.
- [ ] **O-42** 🖥 Edit a document in CWLed, **Save** (uploaded), then edit the same document on the instance, **Rescan** → the instance's version comes in. Edit one in CWLed and disconnect before saving → Rescan with the network back does not overwrite your edit; and a document you edited here (not uploaded) that the instance then **deleted** is kept here, whereas one you had not changed since the last upload or sync is removed with it. If the clock of the instance is wrong by minutes, none of this changes.

### Afterwards

- [ ] **O-19** Quit and start CWLed again → the remote root is still there with its `host:/path` name, and saving a document of it still uploads.
- [ ] **O-20** Right-click the remote root → **Remove from Workspace** → the root goes away; the copy is still on the disk (macOS: `~/Library/Application Support/cwled/remote/<host>/…`). Add the same remote folder again → it reuses that copy
      (a file you changed and could not upload is still there).
- [ ] **O-21** A **detached window** (section **B**) shows the same `host:/path` name for the root; **+ Add a Remote Folder (SSH)** in the side panel of the detached window adds the folder to *that window's* workspace; a document of it saved in either window is uploaded.
- [ ] **O-22** A workflow in the remote folder whose steps are other files of the same remote folder (`run: tools/x.cwl`) opens with its steps (see **O-32**: the tools are copied when it is opened), and clicking the name of a step reveals the tool in the remote root (section **D**).
- [ ] **O-23** All five themes: the dialog, the hosts table, the red error line and the server icon of the root are readable in each (View → Theme).
- [ ] **O-24** `remote_folders` in the user configuration file lists the folders (host, path, mirror, synced); delete the entry by hand and start again → the root keeps its folder but is no longer named `host:/path` and no longer uploads.

## P. The logo and the window that shows while CWLed starts

Only on a real screen can you tell whether it looks right and whether it comes up in time; the automated tests check the pixels, the order of the steps and the settings.

- [ ] **P-01** 🖥 Start CWLed from the terminal (`uv run ./cwled.py`) → within a second a window with the logo shows in the middle of the screen: a **W** of five nodes (light ports at the ends, teal and purple steps, raspberry edges), the name **CWLed**,
      *COMMON WORKFLOW LANGUAGE EDITOR*, a bar and the version at the bottom right. It is there **before** the long wait for the libraries, not after it.
- [ ] **P-02** 🖥 The bar fills while the messages change (*Loading the configuration → Applying the theme → Preparing the workspace → Checking the CWL tools → Opening the window → Ready*). The window stays at least a second, fades out and the main window is in front.
      The corners of the logo window are rounded and see-through (no black corners), also on a second monitor and on a retina screen (sharp, not blurred).
- [ ] **P-03** 🖥 The logo window does not hide an error dialog or the main window: start with a broken tool path (or a workspace folder that cannot be created) → the error is readable.
- [ ] **P-04** `uv run ./cwled.py --no-splash` → no logo window. Same with `CWLED_NO_SPLASH=1 uv run ./cwled.py`. `--version` and `--help` print and exit, without any window.
- [ ] **P-05** **Tools → Configuration → General**: *Show the logo while CWLed starts* is ticked; untick it, press OK, restart → no logo window; `show_splash: false` is in the configuration file. Tick it again → the logo is back.
- [ ] **P-06** 🖥 Start CWLed with a file (`uv run ./cwled.py tests/echo.cwl`) and with `--new-workflow Demo` → the logo shows, then the main window with the document, as usual.
- [ ] **P-07** 🖥 The title of the side panel has the small mark before **CWLed**, aligned with the name and sharp, in all five themes; the Dock/taskbar icon and the window icon of the application are the mark on its dark rounded square (the old icon, the CWL zigzag with the letters, is gone).
- [ ] **P-08** 🖥 A packaged build (`make debug-mac`): the application icon in the Finder and the Dock is the new one (`resources/icons/cwled.icns`), and the logo window shows when the packaged application starts.
- [ ] **P-09** The files in `resources/logo` open in a browser or a vector program: `cwled-mark.svg`, `cwled-mark-plain.svg`, `cwled-logo-dark.svg` (white name, on a dark page) and `cwled-logo-light.svg` (dark name, on a light page); the name is outlines (no font needed).
      The README shows the mark at its top. `uv run python resources/logo/make_logo.py` changes none of the files (`git status` stays clean).

---

## S. The modified marker (`*`) and the "Save changes?" prompt

A bug report from hand-testing: after changing a workflow the `*` did not appear by itself (only after switching to another tab), and a window could be closed without being asked to save.
Cause: the Visual Editor changes the document in place, but the window's "modified" state was refreshed only when the tabs were redrawn. Now the graph announces its changes and the close prompt
looks at the document itself. Test every kind of edit **without switching tabs**, then close.

A second, related problem was found while fixing it: text typed in the **Code** tab is only applied to the document when you leave the tab, so the `*` never appeared while typing, closing from the Code tab
did not ask to save, and **Save did not save the typed text** (the file kept its old content). Now typing marks the document, the close prompt counts it, and Save applies the typed text first (S-17 to S-21).

For each edit: **the `*` appears at once**, both in front of the **tab title** and of the **window title**, with the Visual Editor still showing.

- [ ] **S-01** Connect two ports by dragging from an output port to an input port.
- [ ] **S-02** Select a connection and delete it, or drag it off its port.
- [ ] **S-03** Select a step (or an input/output node) and press **Delete** / **Backspace**.
- [ ] **S-04** Add a step by dropping a tool or workflow on the canvas (from the side panel, **Recent** and Finder).
- [ ] **S-05** Drag from a step's output port into empty canvas (a new workflow output) and from an input port (a new workflow input).
- [ ] **S-06** In the right panel (step inspector): change the **Label**, rename the **ID**, edit a default value, switch an input between **Default / Exposed / Port**, show/hide an optional File port,
      set **Scatter** or **When**, edit the **Hints**, edit the **Description**. Each one marks the document once the edit is committed (the panel applies changes about half a second after you stop typing).
- [ ] **S-07** Double-click a workflow **input** or **output** node, change something in the dialog and press **OK**.
- [ ] **S-08** **Undo by hand** (set the label back to what it was, reconnect what you disconnected): the `*` goes away, because the document is the same as the saved one again.
- [ ] **S-09** **Moving a node** with the mouse does **not** mark the document modified (node positions are not part of the CWL document), and closing does not ask to save because of it.
- [ ] **S-10** After any of S-01 to S-07, **close the tab without switching tabs** (the × of the tab, **File → Close tab**, Cmd/Ctrl+W) → "You have unsaved changes. Do you want to save before closing?" with Yes / No / Cancel.
      **Cancel** keeps the tab with its changes; **Yes** saves and closes; **No** closes without saving.
- [ ] **S-11** The same with **Quit** (Cmd/Ctrl+Q) and with closing the **main window**, and for a document in a **detached window** (close the tab, close the window).
- [ ] **S-12** **Save** → the `*` disappears; reopen the file → all the edits are there.
- [ ] **S-13** After an edit, press the **Git commit** or **Git pull** button of the document toolbar → the document is saved first (these look at the document, not at the marker).
- [ ] **S-14** After an edit, **Tools → Compare with… → The saved version of this document** shows the edit (see **H-16**).
- [ ] **S-15** No false alarms: open one document of each kind (a tool, an expression tool, a workflow with file steps, a workflow with inline steps, a tool with records) and **do nothing** → no `*`, and closing never asks to save.
- [ ] **S-16** Other editors still mark the document at once (check that nothing regressed): App Info fields, the tool editor (inputs, arguments, requirements), the Code tab (type a valid change).
- [ ] **S-17** **Code tab, typing:** type a valid change (add a line `label: Hello` under `class:`) and do **not** leave the tab → the `*` appears at once in the tab and the window title. Delete what you typed →
      the `*` disappears (the text is the applied one again).
- [ ] **S-18** **Code tab, saving:** type a valid change, press **Save** (Cmd/Ctrl+S, or the toolbar button) while still in the Code tab → the file on disk contains the typed text, the `*` goes away; reopen the file → the change is there.
      (Before the fix the file kept its old content.) The same with **Save as…**.
- [ ] **S-19** **Code tab, closing:** type a valid change and close the tab from the Code tab → "Save changes?"; **Yes** saves the typed text, **No** discards it, **Cancel** keeps the tab with the text still there.
- [ ] **S-20** **Code tab, text that is not valid CWL yet** (half a line such as `foo: [unclosed`): the `*` appears; **Save** shows the parse error and does **not** touch the file; closing and answering **Yes** keeps the window open
      (so that the typing cannot be lost) and shows the error; **No** closes it. Leaving the Code tab shows the error and stays on the tab (as before).
- [ ] **S-21** Opening a document, switching between its tabs, and toggling **YAML / JSON** in the Code tab never mark it as modified (filling the editor is not an edit); the Code tab of an untouched document does not make closing ask anything.


---

## U. Run from the editor (Tools → Run tool/workflow...)

The document is run with cwltool in a process of its own, and the Run dialog shows its log as it comes. The automated tests (`pytests/test_run_from_editor.py`) run the real cwltool on `tests/echo.cwl` and on small tools, and check the save-first question, the job template, cancelling, failures and the output list. They cannot see the dialog on a screen, the editor staying responsive, Finder, or the packaged application.
Use a copy of the test documents (see *How to use this list*) for the runs that write files; the job files and output folders go next to the document or into the folder you choose.

- [ ] **U-01** **Tools** menu: **Run tool/workflow...** is right under **Validate tool**.
- [ ] **U-02** No document open (close all tabs), **Tools → Run tool/workflow...** → the "No Document: Please select a document first." warning, as for **Validate tool**.
- [ ] **U-03** Type a change in the Code tab of `echo.cwl` (the `*` appears), then **Tools → Run tool/workflow...** → "Save Before Running?" with **Yes** / **No**. **No** → no dialog, the `*` stays. Run again, answer **Yes** → the document is saved (the `*` goes) and the Run dialog opens.
- [ ] **U-04** A new document that was never saved (**File → New → Command line tool**), then Run → the question; **Yes** → the Save As dialog. Cancel it → no Run dialog. Save it → the Run dialog opens for the saved file.
- [ ] **U-05** The Run dialog is titled **Run echo.cwl**. Its output folder is `echo-run-` followed by the date and time (`YYYYMMDD-HHMMSS`), in the folder of `echo.cwl`.
- [ ] **U-06** **Generate from template** on `echo.cwl` → the box shows YAML with `message:`, the label says *Generated from the template (not saved yet)*, and no file appears next to `echo.cwl` (only `echo.cwl` in the folder).
- [ ] **U-07** **Choose file...** → pick a job file (for example one written with `message: hello`) → its text appears in the box and its path in the field. **Run** → no `echo-job.yml` is created next to the document (the file was used as it is).
- [ ] **U-08** Change the text in the box (`message: bye`), leave **Save the job as echo-job.yml next to the document when it runs** ticked, **Run** → `echo-job.yml` appears next to `echo.cwl` with the changed text. Untick the box and run again → the job is written into the output folder instead.
- [ ] **U-09** 🖥 **Run** `echo.cwl` with `message: hello` → the status says *Running…* and the Run button is disabled; the log fills with cwltool's lines (`[job echo.cwl] …`, *completed success*) while it runs, and the Log box shows no colour codes or boxes.
- [ ] **U-10** 🖥 While a run goes (use a tool that takes a few seconds), the editor stays usable: switch to the Code tab, scroll, type, open another document. Moving the Run dialog and the main window is smooth.
- [ ] **U-11** After **U-09**: the status says *Finished, exit code 0. The results are in …*; the **Result** box shows the output as JSON (`"out": "hello\n"`) and under *Produced files* the line *(none: the outputs are values, not files)*.
- [ ] **U-12** A tool whose output is a file (a `stdout:` output, for example) → after the run, *Produced files* lists the file; **Open output folder** shows the output folder.
- [ ] **U-13** 🖥 **Open output folder** → Finder opens the output folder shown in the Output box (not the document's folder).
- [ ] **U-14** 🖥 A workflow (for example `50-workflow.cwl`, with the job its inputs need: **Generate from template** helps) runs to the end; the Result box shows its outputs and the log shows each step.
- [ ] **U-15** `uppercase.cwl` (an expression tool) with `message: hello` → *Finished*, the result is `"uppercase_message": "HELLO"`. (Needs Node.js on this machine; without it the run fails and the log names Node.js.)
- [ ] **U-16** A job that is not YAML or JSON (for example `message: [unclosed`) → the warning *The job is not YAML or JSON that names the inputs*; nothing runs and the log stays empty.
- [ ] **U-17** An output folder that is an existing file, or an empty output folder field → a warning that names the problem; nothing runs.
- [ ] **U-18** A tool that fails: a CommandLineTool with `baseCommand: [sh, -c]` and `arguments: ["echo oops >&2; exit 3"]`, run with `{}` → the status says *Failed, exit code 1. The log says what went wrong.*; the log shows `oops` and the failure; no error pop-up appears (the failure is not an error dialog); the Result box is hidden; **Run** is enabled again.
- [ ] **U-19** 🖥 **Cancel** during a long run: write a small tool in a scratch folder (`baseCommand: sleep`, one input `seconds: int` with `inputBinding: {position: 1}`, no outputs) and run it with `seconds: 300` → press **Cancel run** → the status says *Stopping...* and then *Cancelled.* within a few seconds; afterwards no `sleep` or `cwltool` process is left (check Activity Monitor or `ps`).
- [ ] **U-20** 🖥 Start the same long run and **close** the dialog (**Close**, Esc or the window's ×) → the run stops within a few seconds, as in **U-19**.
- [ ] **U-21** 🖥 Run the document from a **detached** window (drag its tab out of the main window first): the dialog and the Save question appear over that window, not behind it.
- [ ] **U-22** 🖥 With a long run going, the other documents of the window still respond (their tabs, menus and dialogs); only the document that is running is blocked by the Run dialog.
- [ ] **U-23** 🖥 A packaged build (`make debug-mac`): **Run** `echo.cwl` → it finishes like in **U-09**, and no second CWLed window opens.
- [ ] **U-24** Known gaps (do not report): from the packaged build, **Cancel** stops cwltool itself but not necessarily the tools it started (a source build stops the whole process group, see **U-19**); for a Docker tool, check that its container has stopped after **Cancel**; runs are local only (a document of a remote folder is run from its local copy).

## V. Problems panel, live validation, autocompletion

The **Code** tab of a document now has a **Problems** panel below the editor: the messages of the last check, each with its line (the header counts them, for example *Problems (3)*). While the Code tab is shown, the text is checked 1.5 s after the last edit, in the background (the lines with a problem are underlined in red); the **Check** button checks at once. Words of CWL are offered while you type (after two letters) and with **Ctrl+Space**. The setting is **Tools → Configuration → General → Check the document while typing in the Code tab**.
The automated tests (`pytests/test_problems_panel.py`) cover the parser, the quiet time, the results of earlier texts, the setting and the clicks; the checks below are what a real screen shows.

- [ ] **V-01** 🖥 Open `tests/01-hello-world.cwl`, go to the **Code** tab → below the editor a **Problems (0)** header and the note *No problems found.* (within about two seconds). The panel is at the bottom, the editor above it still gets the height.
- [ ] **V-02** In the Code tab, change `type: string` (line 11) to `type: strin` and stop typing → after about 1.5 s the header reads **Problems (1)** and lists *Line 11: Field 'type' references unknown identifier 'strin' …* (the line of `type:`); that line is underlined in red.
- [ ] **V-03** Keep typing without a pause: the list keeps its previous result; it changes about 1.5 s after the last key, not while you type.
- [ ] **V-04** 🖥 Click the entry → the cursor goes to that line and the editor has the focus; the line is visible even when it is far down the document.
- [ ] **V-05** Put `string` back → after the pause the header reads **Problems (0)** and the note *No problems found.*; the red underline is gone.
- [ ] **V-06** Select all in the editor and delete it → after the pause a message *I'm sorry, I couldn't load this CWL file …* is listed **without** a line number; clicking it does not move the cursor.
- [ ] **V-07** Click the **Problems (n)** header → the list folds away and only the header stays; click again → it comes back.
- [ ] **V-08** A syntax error: type `baseCommand: [echo` (unclosed bracket) on a new line → the list shows a message with the line of the error; nothing is shown as a dialog (the error does not open a window).
- [ ] **V-09** **Tools → Configuration → General**: untick *Check the document while typing in the Code tab (Problems panel)*, press OK. Type an error in the Code tab and wait 5 s → the list does not change and no underline appears. Press **Check** → the result appears. Tick the box again and press OK → typing is checked again.
- [ ] **V-10** Go to the **App Info** tab and change the label, wait 5 s, then go to the **Code** tab → the panel is updated about 1.5 s after the tab is shown (the check starts when the tab is shown, not while another tab is in front).
- [ ] **V-11** 🖥 Type quickly in a long document (the largest workflow you have) with the Code tab in front → typing and scrolling do not stutter visibly while a check runs (the check is in the background; a short pause while it runs is acceptable, a freeze is a bug).
- [ ] **V-12** Type invalid text several times in a row → no modal error dialog opens at any time; the messages only appear in the panel.
- [ ] **V-13** 🖥 Autocompletion: in the Code tab, on an empty line, type `cl` → after the second letter a list opens with *class*, *CommandLineTool* …; arrows choose, Enter inserts the word, Escape closes the list.
- [ ] **V-14** 🖥 **Ctrl+Space** (Command+Space on the Mac is the system's Spotlight; use **Control+Space** there) on an empty line → the list of words opens. If the Mac's input-source shortcut takes Control+Space, the list does not open: note it and use the shortcut from System Settings → Keyboard instead (not a CWLed bug).
- [ ] **V-15** Toggle **JSON** in the Code tab: the autocompletion still offers the words; an error typed in JSON (for example a missing comma) is reported on the line of the JSON text (click the entry → the cursor lands on that line of the JSON).
- [ ] **V-16** A workflow whose step refers to a tool next to it (`run: echo.cwl`, as `tests/50-workflow.cwl`) → no *file does not exist* message in the panel; the workflow's file is checked as a whole.
- [ ] **V-17** Check the folder of the document after a few checks (Finder with **Cmd+Shift+.** shows hidden files, or `ls -a` in Terminal) → no `.cwled-check-…cwl` file is left behind.
- [ ] **V-18** A new document (**File → New**, not saved yet) → typing an error shows the messages in the panel; nothing is written in your workspace folder or home folder (the check uses the temporary folder).
- [ ] **V-19** A document in a folder you cannot write to (a read-only folder, a volume that is locked) → the checks still run and show their messages; the copy goes to the temporary folder.
- [ ] **V-20** The **Tools → Validate** menu item still opens its dialog as before; the Problems panel is not changed by it (it is a separate check; a known gap, see the note in the User guide).
- [ ] **V-21** A document in a **detached** window (drag its tab out) → its Code tab has its own panel, checks in that window, and clicks move that window's cursor.
- [ ] **V-22** 🖥 In each of the five themes (Composer Dark, Light, Midnight, Nord, Solarized Light) the panel, its header and the red underline are readable; the error text of the list is not cut off at the window's width.
- [ ] **V-23** Type an error, and quit (**Cmd/Ctrl+Q**) or close the window within a second of the last key, while the check runs → the application closes without hanging and without an error dialog.

## W. Fix with AI

The automated tests (`pytests/test_fix_with_ai.py`) replace the model by a stand-in, so they send nothing and need no key.
The items marked 🖥 need a real display, and those that send the document need a configured model: its provider and
model in the `llm` section of the configuration, and its API key in the environment or in `cwled.env`.
Use a scratch copy of `tests/echo.cwl` for the items that break the document.

### The entries

- [ ] **W-01** 🖥 In the Code tab of a scratch copy of `tests/echo.cwl`, change `type: string` under `outputs` to `type: strinq`
      and do **not** click **Update**. **Tools → Validate tool** → the error dialog "This tool cannot be validated" lists the
      validator's messages and has a **Fix with AI** button above **OK**.
- [ ] **W-02** **Tools → Suggest a fix for the validation errors** on `tests/echo.cwl` (valid) → "The document is valid: there is
      nothing to fix." and no consent is asked.
- [ ] **W-03** **Tools → Suggest a fix for the validation errors** on the document of W-01 → the consent of W-05 opens at once
      (no second click on the error dialog).
- [ ] **W-04** 🖥 **Tools** menu: "Suggest a fix for the validation errors" is right below "Validate tool".

### Consent and the request

- [ ] **W-05** 🖥 The consent says "The document and the validation errors will be sent to *provider*/*model*." (the ones of
      your configuration) with **Send** and **Cancel**. **Cancel** → the dialog closes and no busy dialog follows.
- [ ] **W-06** 🖥 With **Send** and a configured key: a dialog "Asking *provider*/*model* for a fix..." shows a busy bar and
      **Cancel**; while it waits, menus, tabs and scrolling still work.
- [ ] **W-07** 🖥 **Cancel** while it waits → the dialog closes at once. When the answer comes later, nothing opens and the
      document is unchanged.
- [ ] **W-08** 🖥 Remove the API key (unset the variable, and remove it from `cwled.env`) and use **Fix with AI** → the message
      "API Key Missing" (the message Troubleshoot shows) and nothing else; no consent is asked.
- [ ] **W-09** 🖥 Unset the variable but keep the key in `cwled.env` → the key is read from it and the flow goes on to the consent.

### The answer

- [ ] **W-10** 🖥 A real answer that is a document, with the explanation of the model around it (usual): the suggestion opens; the
      explanation appears nowhere in the Code tab or in the comparison.
- [ ] **W-11** 🖥 An answer without a CWL document (for example the model replies only "I cannot help") → "The answer could not
      be used." and **Details** shows the answer. The Code tab is unchanged.
- [ ] **W-12** 🖥 The Code tab text that is not YAML (for example `class: [unclosed` typed in the Code tab, not updated) → the
      flow still starts; the comparison shows "Not a CWL document: compare the lines" on the left, and the lines are coloured.

### The comparison, Apply and Discard

- [ ] **W-13** 🖥 The comparison shows **Current document ↔ Suggested fix**: the changed lines are coloured on both sides and the
      changed parts are listed on the left (for example `outputs out`).
- [ ] **W-14** 🖥 **Discard** → the Code tab text and the window title (no `*`) are as they were.
- [ ] **W-15** 🖥 **Apply** → the Code tab shows the suggested text, the window title gets a `*`, and the App and Info tabs show
      the change. The comments the model wrote are in the Code tab.
- [ ] **W-16** 🖥 After **Apply**, **Undo** (⌘Z on macOS, Ctrl+Z elsewhere) in the Code tab takes the whole suggestion back in one
      step; the text is what it was before **Apply**.
- [ ] **W-17** 🖥 **Save** after **Apply** → the saved file is the suggestion (the Code tab text the model wrote, with the comments).
- [ ] **W-18** The document that has unsaved changes in the Code tab is the one sent: the suggestion is based on the text
      that is shown, not on the file on disk.

### Automated

- [ ] **W-19** `uv run pytest pytests/test_fix_with_ai.py` → all tests pass (seconds, no network, no key needed).

## X. Container assistant (the Docker image of a tool)

The three buttons under **Docker Image** in the Visual Editor of a CommandLineTool ask the container registries (Docker Hub, quay.io, other registries) only when clicked. Items marked **🖥** need the real network (or a real screen); the automated tests replace the network by a fake registry.

- [ ] **X-01** 🖥 Turn Wi-Fi off, open `tests/09-arguments.cwl` → no message about a registry, the field shows `openjdk:9.0.1-11-slim`, and the buttons **Check image**, **Suggest BioContainers image** and **Pin digest** are under it with an empty line below. Turn Wi-Fi back on; while it was off nothing was requested.
- [ ] **X-02** 🖥 Edit the Docker field and the arguments of the tool, click elsewhere, switch tabs (no button clicked) → no line appears under the buttons and nothing reaches the network (watch with a network monitor such as Little Snitch, or `lsof -i`, if you have one).
- [ ] **X-03** 🖥 Field `ubuntu:22.04` → **Check image** → within a few seconds the line says *Found ubuntu:22.04, digest sha256:…*. Move, resize and switch tabs while it waits: the window keeps responding, and the buttons are greyed out until the answer comes.
- [ ] **X-04** 🖥 Field `quay.io/biocontainers/samtools:1.19--h50ea8bc_0` → **Check image** → *Found …, digest sha256:…*.
- [ ] **X-05** 🖥 Field `quay.io/biocontainers/samtools:no-such-tag` → **Check image** → *… is not in quay.io.*
- [ ] **X-06** 🖥 Field `registry.example.com:5000/app:1` (a host that does not exist) → **Check image** → *Could not reach the registry: registry.example.com did not answer (…)* after a few seconds at most; the window does not freeze.
- [ ] **X-07** 🖥 Wi-Fi off, field `ubuntu:22.04` → **Check image** → *Could not reach the registry* (not a crash, no error dialog, no log entry in red).
- [ ] **X-08** Field empty, or `Ubuntu`, or `two words` → **Check image** → *Not an image reference: …*; no network traffic (X-02 method).
- [ ] **X-09** 🖥 Base command `samtools view`, field empty → **Suggest BioContainers image** → a small dialog lists the newest tags of `quay.io/biocontainers/samtools`, newest first, with the first one selected; at most 20 tags.
- [ ] **X-10** 🖥 In that dialog choose another tag and press **OK** (or double-click it) → the field reads `quay.io/biocontainers/samtools:<tag>`, the line says *Set to …*, and the Code tab shows the same `dockerPull`.
- [ ] **X-11** In that dialog press **Cancel** → the field and the Code tab are unchanged, the line is empty.
- [ ] **X-12** 🖥 Base command `xyzzy-no-such-tool` → **Suggest BioContainers image** → *There is no BioContainers image named xyzzy-no-such-tool on quay.io.* and no dialog.
- [ ] **X-13** Base command empty (no rows in **Base Command**) → **Suggest BioContainers image** → *Set the base command first …*; no network traffic.
- [ ] **X-14** 🖥 Base command `/usr/bin/Samtools view` (a path and a capital letter) → **Suggest BioContainers image** lists the `samtools` tags (the directory and the case are ignored).
- [ ] **X-15** 🖥 Wi-Fi off → **Suggest BioContainers image** → *Could not reach the registry* and no dialog.
- [ ] **X-16** 🖥 Field `ubuntu:22.04` → **Pin digest** → the field reads `ubuntu@sha256:…` (the tag is gone from the field), the line says *Pinned ubuntu:22.04 to sha256:…* (the tag stays in view there), and the Code tab shows `dockerPull: ubuntu@sha256:…`; the document is marked as modified.
- [ ] **X-17** After X-16 **Pin digest** is greyed out, with a tooltip saying the image is already pinned; **Check image** on the pinned field says *Found … digest sha256:…* (the same digest).
- [ ] **X-18** Retype the field after X-16 (for example `ubuntu:22.04`) → **Pin digest** is enabled again; the pinned value is gone (undo by retyping).
- [ ] **X-19** 🖥 Wi-Fi off, field `ubuntu:22.04` → **Pin digest** → the field does not change, the line says *Could not reach the registry …*, and **Pin digest** is greyed out; the tooltip (hover) gives the same reason. Type a different image → it is enabled again.
- [ ] **X-20** Field empty or `Ubuntu` → **Pin digest** is greyed out; the tooltip says *Not an image reference: …*.
- [ ] **X-21** 🖥 Save after X-16 and reopen the file → the `dockerPull` in the saved file is `ubuntu@sha256:…`; **Tools → Validate tool** accepts the tool (`cwltool --validate`).
- [ ] **X-22** 🖥 Proxy: start CWLed with `HTTPS_PROXY=http://127.0.0.1:9` (a port with nothing listening) and click **Check image** on `ubuntu:22.04` → *Could not reach the registry* (the request went through the proxy, which refused it). Without the variable the check works again.
- [ ] **X-23** 🖥 Dark and light themes, a narrow window: the three buttons, the line under them and the tooltips are readable; the line wraps instead of widening the Visual Editor.
- [ ] **X-24** Known limits (do not report as bugs): private registries that need a login are *could not reach*; Docker Hub and quay.io may rate-limit a burst of checks; **Pin digest** keeps only `image@digest` (the tag is not written into the field); for a multi-platform image the digest is the one of the image index; the digest of a *Check* on a `@sha256:` image is looked up in the same registry.

---

## T. Automated tests, CI and documentation

- [ ] **T-01** `uv sync --group dev && uv run pytest` on your machine → all tests pass (about a minute; no window appears, nothing of your configuration, logs or caches is touched).
- [ ] **T-02** Run the tests from a copy of the repository that lives **inside** the operating system's temporary directory → expect failures of tests that check tab titles of documents opened from there
      (a known quirk, see **N**); inside your home directory they pass.
- [ ] **T-03** 🖥 Push the branch (or open a pull request) → the **Tests** workflow (`.github/workflows/tests.yml`: Ubuntu, Python 3.10, offscreen) starts and passes. It has never run on GitHub; if it fails
      on a missing Qt system library, add it to the `apt-get install` line.
- [ ] **T-04** The release workflow (`build-release.yml`) is unchanged and still builds (`uv sync --group dev` now also installs `pytest`).
- [ ] **T-05** **Help → User Guide** opens in the browser with the new sections (*Detached Windows*, *Comparing Documents*, the side panel, the workflow Visual Editor): read them against what you see in the application
      and note any statement that is wrong or any behaviour that is missing from it.
- [ ] **T-06** `DEV.md` (*Automated tests*) describes how to run the tests and links to this file.
- [ ] **T-07** `tests/` contains **only CWL documents** (and their input files): no Python files, no `conftest.py`. The test code is in `pytests/`, and `uv run pytest pytests/test_graph_canvas.py -k pan` (the example in `DEV.md`) runs.
- [ ] **T-08** `uv run pytest pytests/test_ssh_config.py pytests/test_remote_folders.py` passes (seconds): the SSH configuration reader and the remote folders, tested with a shell on this machine instead of `ssh`. They never read your `~/.ssh` or touch the data folder of the application.

---

## R. Quick regression pass (older behaviour that the changes touched)

- [ ] **R-01** Open, edit, **Save**, **Save As** (YAML and JSON) and **Reload** a tool and a workflow in the main window; the `*` marker follows the changes.
- [ ] **R-02** Reorder tabs by dragging inside the tab bar; close tabs with ×, **File → Close tab** and Cmd/Ctrl+W.
- [ ] **R-03** **File → Recent** and the Recent list in the side panel and on the Welcome tab open the right files; a recent file that no longer exists is reported and removed.
- [ ] **R-04** Add and remove workspace folders; the first folder and the current folder behave as before (status bar, default folder of Save As, working directory).
- [ ] **R-05** A file cannot be saved outside the workspace folders of **its window**; the message names the folders.
- [ ] **R-06** Dialogs (Configuration, Draft CommandLineTool, Input/Output/Step dialogs, message boxes) appear over the window you are using, not behind another window.
- [ ] **R-07** **Tools** menu: Validate, Run tool/workflow, Generate template, Pack workflow, Repackage workflow, Save workflow documentation, Upgrade version, Troubleshoot — each acts on the active document of the window you use it in.
- [ ] **R-08** Git buttons of the document toolbar (commit / push / pull) use the folder of the document (or of the current workspace folder of its window).
- [ ] **R-09** Dragging a file from the side panel or **Recent** onto a workflow canvas still adds a step; this also works in a detached window.
- [ ] **R-10** The Info tab's bottom ribbon (format / created / modified) and the Code tab's "File URI" row look normal at full width.
- [ ] **R-11** Open a **large** real workflow (dozens of steps): opening, panning, zooming, selecting and the step inspector stay responsive.
- [ ] **R-12** Quit and relaunch several times with documents open → no crash on quit (see the note in **K-10**), no leftover windows, no zombie process.
- [ ] **R-13** Logs: look at the log directory (`user_log_path`, shown on the Welcome tab) after a long session → no repeated errors or tracebacks from the new features.
- [ ] **R-14** A workflow in a **folder with a space, a `%` or an accent in its name** (for example `~/My Pipelines/workflows/…` whose steps run `../../tools/x.cwl`) opens with its steps (no "File does not exist … %20 …" error), clicking a step name finds its tool, and **Save** leaves the `run:` paths as they were.

---

## How to report a failure

Item id, platform (macOS version, Retina or not, number of monitors, trackpad or mouse), the exact steps, what you expected and what you saw, plus the newest file of the log directory
(shown on the Welcome tab). For a failure that can be reproduced without a screen, add a test to `pytests/` (see [DEV.md](../DEV.md), *Automated tests*).
