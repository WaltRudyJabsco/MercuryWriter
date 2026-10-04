# Mercury Writer

**A small, local-first writing studio for novels and long-form fiction.**

Mercury Writer is built around a simple idea: the manuscript should remain at
the center of the screen, the files should remain yours, and useful AI should be
available without turning the writing program into a cloud service.

Mercury is a self-contained browser writing application with a small Python
standard-library companion server. It combines a serious manuscript editor,
book-like 6 × 9 preview and PDF output, local Ollama AI, revisioned project
storage, a multi-project Mercury Library, and a terminal/Neovim workflow.

There is no required Mercury account, database, hosted manuscript service,
`pip install`, `npm install`, or build process.

![Mercury Writer editor](screenshots/MercuryWriter_Dark_Editor.png)

![Mercury Writer Book View](screenshots/MercuryWriter_Light_Bookview.png)

![Mercury Writer AI assistant](screenshots/MercuryWriter_Custom_AI.png)

## What Mercury includes

- Chapter/scene manuscript tree with collapsible chapters
- Distraction-free Editor and 6 × 9 Book View
- Scene notes, targets, statistics, Find, Undo/Redo, Focus, themes, and zoom
- Full manuscript, chapter, or scene output scope
- Portable `.mercury`, TXT, Markdown, and 6 × 9 PDF export
- Continuous browser autosave plus server recovery history
- Revision identity, immutable revision copies, and conflict preservation
- Multi-project Mercury Library with stable project IDs
- Explicit local/offline manuscript zone at `~/Mercury Writer Documents`
- Local, cache, and Fabric-only availability policy
- Local Ollama AI with selectable models and optional web search
- Fabric-aware terminal library and local Neovim editing
- Responsive desktop, tablet, and phone layouts

## The mental model

Mercury keeps source code, the installed app, and writing data separate:

```text
~/Local-Labs/Mercury-Writer/       source · Git checkout
~/Applications/Mercury-Writer/    installed app on macOS
~/.local/share/mercury-writer/    installed app on Linux
~/Mercury Writer Documents/       manuscripts · offline replicas
```

The Mercury Library is not a list of autosaves. One manuscript has one stable
project identity, many revisions, and potentially several physical replicas.

Deleting a file in `Mercury Writer Documents` is therefore **not** the same as
deleting a project. An `always-local` replica may be repaired from canonical
state. Use Mercury's explicit library actions when removal is intentional.

### Remove Local Copy

**Remove Local** changes that project's availability to `fabric-only` on the
current Mercury node and moves its Documents replica to `.mercury-trash`. The
canonical Library project remains available.

Terminal equivalent:

```bash
mercury remove-local "American Mercury"
```

### Delete Project

**Delete** removes the project from the Mercury Library and moves both its
canonical library directory and Documents replica to recoverable Mercury trash.
It requires typing `DELETE`. Mercury does not immediately erase the manuscript.

Terminal equivalent:

```bash
mercury delete "American Mercury"
```

## Git workflow

Clone Mercury once on every development machine into the same conventional
source location:

```bash
mkdir -p ~/Local-Labs
cd ~/Local-Labs
git clone https://github.com/WaltRudyJabsco/Mercury-Writer.git
cd Mercury-Writer
```

After a new version is pushed to GitHub:

```bash
cd ~/Local-Labs/Mercury-Writer
git pull
bash install_mercury.sh
```

The Git checkout is application **source**, not manuscript storage. Installer
updates must not remove `~/Mercury Writer Documents` or Mercury's state/history.

## Install

From the repository or an unpacked release:

```bash
bash install_mercury.sh
```

Mercury installs to `~/Applications/Mercury-Writer` on macOS and
`~/.local/share/mercury-writer` on Linux. The installer can prepare Python,
Ollama, launchers, and optional Ollama Web Search credentials.

Run the server directly when desired:

```bash
python3 mercury_server.py
```

Then open `http://127.0.0.1:8765`.

## Terminal Mercury

The `mercury` sidecar is a compact control surface:

```text
mercury
mercury library
mercury edit
mercury edit "American Mercury"
mercury edit "American Mercury" Frank
mercury remove-local "American Mercury"
mercury delete "American Mercury"
mercury doctor airplane
```

`mercury edit` selects a Library project, materializes a local Markdown
workspace, opens the local `$EDITOR` (preferring Neovim), and commits changed
scenes against the exact parent revision. A stale concurrent edit is preserved
as a conflict instead of overwriting canonical work.

`mercury doctor airplane` reports manuscripts physically present in the local
Documents zone.

## Local AI

Mercury discovers compatible models from Ollama. AI context can be scoped to
selected text, the current scene, chapter, whole manuscript, or no manuscript
context. With web search off, prompts and manuscript context stay on the
configured Ollama path. Web search is optional and requires an Ollama API key.

Mercury can use local models on the same machine or a reachable Fabric/Ollama
host. AI availability is separate from manuscript availability: losing the
Tailnet should not make an offline manuscript unreadable or uneditable.

## Book View and PDF

Book View uses fixed 6 × 9 page geometry for reading rhythm and approximate page
flow. Mercury's preferred PDF path uses a local Chrome/Chromium-family browser
when available, with its built-in fallback renderer otherwise.

## Private mobile access

![Mercury Writer on iOS through Tailscale](screenshots/MercuryWriter_iOS_Tailscale.png)

Mercury's browser interface can be served privately across a Tailscale tailnet,
letting an iPad, iPhone, or another computer use the writing interface while a
larger machine provides the Mercury server and Ollama models.

Do not confuse private Tailnet access with offline availability. Projects marked
for local availability should also exist in `~/Mercury Writer Documents` on the
machine you intend to use without the network.

## Files and safety

Mercury deliberately uses several layers:

```text
continuous      browser local autosave
periodic        server recovery history
canonical       revisioned Mercury Library
offline         Mercury Writer Documents replica
portable        explicit .mercury project file
```

Revision conflicts preserve both branches. Duplicate project cleanup archives
the removed identity first. Explicit project deletion uses recoverable trash.
These systems are complementary rather than substitutes for ordinary backups.

## Updating

With the recommended Git checkout:

```bash
cd ~/Local-Labs/Mercury-Writer
git pull
bash install_mercury.sh
```

Application updates and manuscript data are intentionally separate.

## Requirements

Required:

- modern browser
- Python 3

For local AI:

- Ollama
- at least one compatible chat model

Optional:

- Chrome/Chromium-family browser for the preferred PDF path
- Ollama API key for web search
- Tailscale for private Fabric access
- Neovim for the terminal editing workflow

Mercury's Python server uses the standard library and the application has no
required third-party Python or JavaScript packages.

## Screenshots

The repository README expects these existing image paths:

```text
screenshots/MercuryWriter_Dark_Editor.png
screenshots/MercuryWriter_Light_Bookview.png
screenshots/MercuryWriter_Custom_AI.png
screenshots/MercuryWriter_iOS_Tailscale.png
```

## Credits

Mercury Writer was built around the conviction that a serious writing tool can
still be small, understandable, local, and owned by the person doing the
writing.

**The manuscript is the product. The software should get out of its way.**
