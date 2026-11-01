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
