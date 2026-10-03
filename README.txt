Mercury Writer 1.3.1

Mercury Writer is a local-first writing studio: browser writing application, small Python server, local/distributed Ollama intelligence, durable recovery, and an optional Markdown/Neovim workspace.

#Core files

Mercury_Writer_1_3_1.html   browser application
mercury_server.py           server, AI bridge, PDF, recovery, workspace
mercury                     terminal/Neovim sidecar
install_mercury.sh          macOS/Linux installer
mercury_ai.json             optional AI-host configuration

A `.mercury` file is structured project data containing chapters, scenes, text, notes, settings and IDs. It is not one giant Markdown file.

#Saving and recovery

Mercury has three independent safety layers: continuous browser autosave; changed server recovery snapshots about every five minutes (plus early/page-hide saves); and explicit portable `.mercury` saves. Server snapshots live in `history/<project-name>/`, and the latest server project is mirrored at `state/current.mercury`. The newest 100 changed snapshots are retained per project.

#Markdown / Neovim workspace

Mercury 1.3 can project the current manuscript into ordinary Markdown files under `workspace/<project>/manuscript/`, grouped by chapter and scene. The `.mercury` project remains canonical; Markdown files carry stable Mercury scene IDs for round-tripping.

mercury edit
mercury edit Frank
mercury sync
mercury workspace
mercury status

`mercury edit` refreshes the workspace, opens `$EDITOR` (Neovim when available), and imports changed scene text/title when the editor exits. The browser Project panel also provides **Refresh Markdown Workspace** and **Import Workspace Changes**. Import currently round-trips scene title and text; chapter/scene creation, deletion, and reordering remain browser operations in 1.3.

#AI / Fabric

Mercury remains standalone. It discovers reachable Ollama models and remembers its own choice. When explicit LOOK/Fabric preferences are available, they become the preferred initial model/host. Supported environment hooks: `FABRIC_MODEL`, `FABRIC_OLLAMA_HOST`, `LOOK_MODEL`, `LOOK_OLLAMA_HOST`. Known LOOK JSON settings locations are also checked. Fabric may choose the intelligence; Mercury owns manuscript context and writing behavior.

#Navigation

Book View: arrows move pages; Shift+Up/Down move pages; Shift+Left/Right jump first/last. Editor View: Shift+Up/Down page through the manuscript; Shift+Left/Right jump beginning/end.

#Linux layout

~/.local/share/mercury-writer/    application/server
~/.local/bin/mercury-writer       web-app launcher
~/.local/bin/mercury              terminal/Neovim sidecar
~/.local/bin/mercurycast          Mercury + Tailscale launcher
~/.config/mercury/service.json    loose discovery descriptor
~/.zsh_secrets                    protected optional secrets

On macOS the default installation remains `~/Applications/Mercury-Writer`; the sidecar is installed at `~/.local/bin/mercury`.

#Existing features preserved

Book View/PDF, themes, Find, autosave, `.mercury` save/open, TXT/Markdown export, responsive phone/tablet/desktop layouts, AI context controls, selective web search, server recovery, Fabric-aware model selection, and Tailscale/Mercurycast remain intact.

#Design rule

The browser remains the polished writing application. Neovim is not reimplemented. Fabric is not embedded. Mercury exposes small explicit interfaces to both while remaining independently usable.


#1.3.1 canonical revision safety

Mercury Server is now the authority for the live manuscript. Browser Mercury and
the Markdown/Neovim workspace are clients of that state.

Every accepted canonical change records:

revision_id       sortable timestamp + UUID entropy
parent_revision   revision the editor started from
created_at        offset-aware local timestamp
content_sha256    full SHA-256 of canonical project content
source            browser / nvim / bootstrap

Canonical revision metadata is stored in `state/revision.json`; immutable
revision copies are stored under `state/revisions/`.

The browser commits edits to the server after a short debounce and checks for
new canonical revisions every two seconds while visible. A Neovim workspace
records the revision it was projected from. On `:wqa`, `mercury edit` imports
against that exact parent revision.

If another editor has advanced the manuscript in the meantime, Mercury does not
choose a winner. It preserves the incoming branch under `state/conflicts/` and
keeps the current canonical manuscript intact. Recovery snapshots and browser
localStorage remain independent additional safety layers.

This revision ledger is intentionally separate from Git. The Markdown workspace
is Git-friendly and can later be checkpointed to a private bare Git remote
without making Git part of Mercury's live synchronization protocol.
