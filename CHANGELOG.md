# 1.6.7 — Terminal Color and Clean Exit

- Restore immediate Library input after a nested Mini session; q no longer waits for Enter.
- Force a full Library redraw after the editor and restore terminal input settings on exit.
- Accept q, Q and Ctrl-Q in the Library.
- Apply a broader terminal palette: blue headers, gold navigation, violet clips, red quit/delete, distinct mode badges and light writing text.
- Use explicit 256-color pairs with eight-color and monochrome fallbacks.
- Highlight active panes, selections and navigator boundaries in Mini.

# 1.6.6 — Clear Terminal Commands

- Wrap Library, Trash and Mini command bars and contrast shortcut keys with descriptions.
- Reserve footer space so long command lists do not overlap projects or writing.
- Include Ctrl-B and show Mini hints for the current editing/navigation mode.
- F1 opens full scrollable help in any mode; normal-mode ? opens help while insert-mode ? stays text.
- Keep editing mode and selection intact through help; Ctrl-B also works from tree and command entry.
- Explain local clipboard scope in the web shelf; remote-access errors no longer look like an empty history and link to local Mercury.

# 1.6.5 — Clipboard in Both Views

- The browser Clipboard button opens searchable LOOK clips with previews and explicit insertion.
- Insert into the upper or lower writing pane at its remembered selection; reject insertion if the project/pane changed.
- The saved-clip API accepts only explicit same-origin requests on localhost; no system clipboard polling or new history syncing.

# 1.6.4 — Writing Keys and LOOK Clips

- Page Up/Down retains the cursor’s screen position and preferred display column.
- Home/End, Ctrl-Home/End, Shift selection and Ctrl-A work across writing modes.
- Shift selections can be replaced by typing or deleted; visual mode remains available.
- Ctrl-C/X/V uses the system clipboard, with an internal register fallback.
- Copied/cut text joins the installed local LOOK clip shelf; Ctrl-B or normal-mode P inserts a saved clip.
- Clipboard actions remain explicit; no capture preference changes or clipboard-history syncing.
- Recognize modified keys through terminfo and common ANSI terminal sequences.

# 1.6.3 — Mini by Default

- Selecting a Library project and `mercury edit` now use Mini by default.
- Direct `mercury --editor mini`, `--editor nvim` and `--editor nvim-desk` open the Library with that editor selected.
- Library subcommands accept editor/split flags too; editor names are case-insensitive.
- The Library shows the selected editor and preserves that choice when opening projects.
- Neovim variants remain explicit options; existing MERCURY_EDITOR preferences are respected.

# 1.6.2 — Your Neovim

- Restore configured Neovim and the chapter/scene directory browser as the default.
- Keep the custom layout as `--editor nvim-desk`; mini remains opt-in when Neovim is available.
- Native `--split` opens two horizontal scene buffers using ordinary Neovim.
- Named chapter/scene workspaces retain shared commits, conflict protection and recovery.
- Continue recovering older numbered-file sessions without moving or replacing their drafts.

# 1.6.1 — One Library

- Open now shows a searchable Mercury Library; Import file is separate.
- Browser and terminal library views emphasize project names and offline readiness.
- `mercury open` opens the browser Library without a terminal project picker.
- Read-only opens, unchanged fields and recovery timers no longer mint revisions.
- A fresh empty library offers New/Import instead of autosaving the starter sample.
- Document physical storage, shared identities and the explicit FabBack backup scope.

# 1.6.0 — Two Places

- Two stacked browser writing panes, independent manuscript navigation, resizing,
  same-scene mirroring and Swap for upper-pane scene tools.
- Focused Neovim desk and optional small built-in modal terminal editor.
- Separate recoverable terminal sessions, live commits and explicit recovery.
- Shared browser/CLI/Library/workspace revision heads, thread/process writer
  serialization, and immutable snapshots as authoritative data.
- Pending offline browser recovery and protection against late save/poll replies.
- Opt-in ancestry-based exchange through paired Fabric, offline Documents
  replicas, explicit conflict resolution and local deletion exclusions.
- Factory reset retains its safety archive and disables sync.
- Optional installed Fabric inference and web research; separate Mercury memory.
- Stable project links for LOOK Notes and a minimal verified bundle installer.
- Local CLI discovery, personal AI config preservation and public-only assets.

# 1.5.4 — Fabric Reset / Trash Recovery

Reset safety archives and epochs, doctor inspection, recoverable Library
deletion, browser writing and Neovim manuscript editing.
