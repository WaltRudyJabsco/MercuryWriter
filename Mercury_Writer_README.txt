Mercury Writer

A small, local-first writing studio for novels and long-form fiction.

Mercury Writer is a deliberately compact writing application built
around a simple idea: the manuscript should remain the center of the
screen, the files should remain yours, and useful AI should be available
without turning the writing program into a cloud service.

Mercury runs as a self-contained browser application with a tiny Python
companion server. Your manuscript is continuously saved in the browser,
can be saved as a portable .mercury project, and can be exported as
plain text, Markdown, or a book-like 6 × 9 PDF. The optional AI
assistant runs against models installed locally with Ollama. Web search
is optional and only used when you turn it on.

  Mercury Writer 1.2.7 is intentionally dependency-light. The Python
  server uses only the Python standard library. There is no pip install,
  npm install, build process, database, account, or cloud manuscript
  storage.

What Mercury includes

-   Chapter and scene manuscript tree with collapsible chapters
-   Distraction-free manuscript editor
-   Scene notes, targets, project statistics, and word counts
-   Book View with fixed 6 × 9 page geometry
-   Adjustable editor and Book View zoom
-   Left, center, right, and justified paragraph alignment
-   Output scope: entire manuscript, current chapter, or current scene
-   Continuous browser-local autosave
-   Portable .mercury project files
-   TXT and Markdown export
-   6 × 9 PDF export with browser-quality rendering when Chrome/Chromium
    is available and a built-in fallback renderer when it is not
-   Find, Undo/Redo, Focus mode, themes, and keyboard shortcuts
-   Responsive desktop, tablet, and phone layouts
-   Local Ollama AI assistant with selectable installed models
-   AI context controls for selected text, scene, chapter, manuscript,
    or no manuscript context
-   Replace-selection workflow with normal Undo support
-   Optional Ollama Web Search context
-   No required cloud account for writing or local AI

The architecture

Mercury is intentionally simple:

    Mercury_Writer_1_2_7.html   The writing application
    mercury_server.py           Small local server + Ollama/PDF bridge

Most of Mercury lives in the single HTML file. The Python server serves
that file locally, talks to Ollama, optionally requests Ollama Web
Search results, and handles PDF export.

The server uses only Python’s standard library. You do not need to
install Python packages with pip.

------------------------------------------------------------------------

Quick Start — macOS

These instructions are written for someone who is comfortable copying
commands into Terminal but does not otherwise need to be a Terminal
user.

1. Put Mercury in a folder

Download or clone Mercury so these two files are together:

    Mercury_Writer_1_2_7.html
    mercury_server.py

Open Terminal, then move into that folder. An easy way on macOS is to
type cd (including the space) and drag the Mercury folder from Finder
into the Terminal window:

    cd /path/to/Mercury-Writer

2. Install Homebrew, if you do not already have it

First check:

    brew --version

If that prints a Homebrew version, skip to the next step.

If brew is not found, install Homebrew with its official installer:

    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

At the end of installation, Homebrew may print a command that adds
Homebrew to your shell PATH. Run the command it gives you. Then close
and reopen Terminal.

Verify:

    brew --version

3. Install Python and Ollama

Mercury’s launcher is a Python 3 program, and its local AI uses Ollama:

    brew install python ollama

Start Ollama now and automatically when you log in:

    brew services start ollama

Verify both:

    python3 --version
    ollama --version

4. Download a local writing model

Mercury automatically discovers the models installed in Ollama and shows
them in its AI model menu.

For most modern Macs with 16 GB of unified memory or more, the tested
default is Qwen3 8B:

    ollama pull qwen3:8b

For an 8 GB machine, or if you want something lighter and faster, try
Qwen3 4B:

    ollama pull qwen3:4b

You can install both:

    ollama pull qwen3:8b
    ollama pull qwen3:4b

The Ollama downloads are roughly 5.2 GB for Qwen3 8B and 2.5 GB for
Qwen3 4B. Actual memory use while running is higher than the model file
alone, so these RAM recommendations are practical starting points rather
than hard requirements.

Mercury is not locked to Qwen. Any compatible local Ollama chat model
that appears in Mercury’s model menu can be selected.

5. Launch Mercury

From the Mercury folder:

    python3 mercury_server.py

Then open:

    http://127.0.0.1:8765

in your browser.

Keep the Terminal window open while using Mercury. To stop the server,
return to Terminal and press:

    Control-C

A convenient launch command

If your Terminal is already in the Mercury folder, this is all you need
on future launches:

    python3 mercury_server.py

If you keep Mercury in a permanent folder, you can also launch it from
anywhere by giving Python the full path:

    python3 "$HOME/path/to/Mercury-Writer/mercury_server.py"

Replace the example path with the actual location of your Mercury
folder.

------------------------------------------------------------------------

Optional: Web Search for the AI assistant

Mercury’s AI is local by default. Checking Web search lets the local
model receive current search results through Ollama’s Web Search API.

This requires an Ollama API key. Create a key in your Ollama account,
then add it to your shell environment.

For the default macOS zsh shell:

    echo 'export OLLAMA_API_KEY="PASTE_YOUR_OLLAMA_API_KEY_HERE"' >> ~/.zshrc
    source ~/.zshrc

Replace the placeholder with your actual key.

You can confirm that the variable exists without printing the secret
itself:

    if [[ -n "$OLLAMA_API_KEY" ]]; then echo "Ollama API key is set"; else echo "Ollama API key is not set"; fi

Then restart Mercury:

    python3 mercury_server.py

The Web search checkbox in Mercury is optional and remembers your
preference in that browser. When it is off, the AI request stays local
between Mercury and your local Ollama service.

  Do not commit your Ollama API key to GitHub. Keep it in your local
  shell environment, not in Mercury’s source files.

------------------------------------------------------------------------

Optional: Better PDF rendering

Mercury can create a 6 × 9 PDF without installing a Python PDF package.

For its highest-fidelity PDF path, Mercury can use a locally installed
Chrome/Chromium-family browser to render the same paginated HTML used by
Book View. If a supported browser renderer is not available, Mercury
automatically falls back to its built-in PDF generator.

So Chrome is optional, not a Mercury dependency.

------------------------------------------------------------------------

Using Mercury

Start with the manuscript tree

The left side of Mercury contains chapters and scenes. Add chapters or
scenes as the manuscript grows, rename them freely, and collapse
chapters when you want a cleaner outline.

Selecting a scene loads it into the editor. Scene text, notes, and
targets belong to that scene.

Write in Editor View

Editor View is the normal drafting environment. The − and + controls
change editor magnification without changing the manuscript itself.

Mercury continuously saves the current project in browser local storage.
The status bar reports the local save state.

Browser autosave is convenient recovery, but it is not a substitute for
keeping project files on disk. Use Save / Export → Mercury Project
regularly.

Use Book View

Book View turns the manuscript into a book-like 6 × 9 preview. It is
useful for reading rhythm, paragraph density, scene breaks, and
approximate page flow without leaving the writing environment.

Book View has its own zoom setting. Zoom changes the on-screen display,
not the physical 6 × 9 page geometry.

The first page includes the project title and author.

Chapters, scenes, and output scope

Mercury can operate on:

-   All — the complete manuscript
-   Chapter — the chapter containing the active scene
-   Scene — only the active scene

The selected output scope applies to portable text/Markdown output, Book
View, and print/export workflows where appropriate. The .mercury project
file always saves the complete project.

Paragraph alignment

Normal prose is left aligned and requires no special markup.

Center, right, and justified paragraphs use Mercury’s small Markdown
extension internally:

    ::: center
    Centered text
    :::

The same form works with right and justify. Mercury’s Book View and PDF
paths understand these blocks.

Save and recovery

Mercury has two complementary save systems:

Browser autosave continuously preserves the current project in that
browser.

Mercury Project creates a portable .mercury file on disk. This is the
file to back up, move to another computer, put in cloud storage, or keep
under your own versioning system.

When you create a new manuscript, Mercury also keeps the previous
project as a recoverable browser snapshot.

Export

Mercury can export:

-   .mercury — complete editable Mercury project
-   .txt — clean manuscript text
-   .md — Markdown manuscript
-   .pdf — 6 × 9 book-style PDF

For long-term safety, keep .mercury project files in addition to any PDF
or text exports.

------------------------------------------------------------------------

Local AI assistant

The AI panel is a writing companion, not a required part of Mercury.

Mercury asks the local Ollama service which models are installed and
lets you choose among them. The last selected model is remembered in the
browser.

You can give the assistant different amounts of manuscript context:

-   Selected text — only the current editor selection
-   Current scene
-   Current chapter
-   Whole manuscript
-   No manuscript context

This makes it possible to ask narrowly scoped questions without
automatically sending the entire manuscript to the model.

Typical uses include:

    What is unclear in this scene?

    Give me three ways this transition could be stronger without rewriting it.

    Check this selected paragraph for continuity problems.

    Summarize what this chapter establishes about the character.

    Find repeated ideas in the manuscript.

Assistant replies support lightweight Markdown. You can copy a reply or
replace the currently selected editor text with the reply; replacements
participate in the editor’s normal Undo history.

Local means local

With Web search off, Mercury sends the prompt and selected manuscript
context to the Ollama server running on your machine.

With Web search on, Mercury additionally sends the search query to
Ollama’s Web Search API and gives the returned web context to the local
model. Do not enable Web Search for material you do not want used as a
web-search query.

------------------------------------------------------------------------

First launch

A completely fresh browser opens a small fictional sample manuscript,
The Last Light by Morgan Hale. It exists only to make Mercury’s
manuscript tree, notes, editor, and Book View immediately visible.

Choose New Project when you are ready to begin. A new project starts
clean:

    Untitled Novel
    └── Chapter 1
        └── Scene 1

------------------------------------------------------------------------

Keyboard and workflow notes

Mercury includes familiar browser/editor conventions for Undo, Redo,
Find, and text editing. The in-app Keyboard shortcuts panel is the
authoritative quick reference for the current build.

A useful working rhythm is:

1.  Draft in Editor View.
2.  Use scene notes for reminders rather than putting scaffolding into
    the prose.
3.  Read periodically in Book View.
4.  Save a .mercury project file at meaningful milestones.
5.  Use the local AI selectively when critique, continuity checking,
    summarization, or alternatives are useful.
6.  Export a 6 × 9 PDF when you want to read the work away from the
    editor.

------------------------------------------------------------------------

Troubleshooting

brew: command not found

Homebrew is either not installed or its shell setup step was not
completed. Re-run the Homebrew installer and follow the shellenv
instructions it prints.

python3: command not found

Install Python:

    brew install python

ollama: command not found

Install Ollama:

    brew install ollama

Then start its background service:

    brew services start ollama

Mercury says Ollama is unavailable

Check that Ollama is running:

    ollama list

If needed:

    brew services restart ollama

Then reload Mercury.

The AI model list is empty

Install at least one model:

    ollama pull qwen3:8b

or:

    ollama pull qwen3:4b

Then reload the AI panel or Mercury.

Web Search does not work

Confirm that the API key is available to the shell that launches
Mercury:

    if [[ -n "$OLLAMA_API_KEY" ]]; then echo "Ollama API key is set"; else echo "Ollama API key is not set"; fi

If you just edited ~/.zshrc, either run:

    source ~/.zshrc

or open a new Terminal window before launching Mercury again.

I want to test the new-user experience

Use a Private/Incognito browser window. Mercury’s manuscript autosave
and UI preferences are stored in browser local storage, so a private
window is an easy clean-room test without deleting your normal
manuscript state.

------------------------------------------------------------------------

Files and privacy

Mercury is local-first by design.

-   Manuscript autosave lives in the browser’s local storage for the
    Mercury site.
-   .mercury files are ordinary files you explicitly save.
-   Local AI requests go to the Ollama service on your machine.
-   Web Search is opt-in and requires an Ollama API key.
-   Mercury has no user account system, database, telemetry system, or
    required manuscript cloud.

As with any writing software, keep backups of work you care about.
Browser storage is useful recovery storage, not archival storage.

------------------------------------------------------------------------

Updating Mercury

For a simple release, replace the Mercury HTML and Python server files
with the newer versions while keeping your saved .mercury manuscript
files.

Before updating, save a fresh .mercury project file.

------------------------------------------------------------------------

Requirements

Required for the full local application

-   A modern web browser
-   Python 3
-   Ollama
-   At least one locally installed Ollama model if you want AI features

Optional

-   Ollama API key for Web Search
-   Chrome/Chromium-family browser for the highest-fidelity PDF
    rendering path

Mercury itself has no third-party Python or JavaScript package
dependencies.

------------------------------------------------------------------------

Suggested repository layout

    Mercury-Writer/
    ├── Mercury_Writer_1_2_7.html
    ├── mercury_server.py
    ├── README.md
    ├── LICENSE
    └── screenshots/
        ├── editor.png
        ├── book-view.png
        └── ai.png

For a public GitHub release, you may also want to provide a ZIP
containing the HTML, mercury_server.py, and a plain-text copy of this
README.

------------------------------------------------------------------------

Notes for other platforms

Mercury’s application code is not inherently macOS-specific: it is HTML
plus a Python standard-library server, and Ollama supports additional
platforms. The setup commands above are intentionally focused on macOS
because that is the currently tested installation path for this project.

If you add Windows or Linux installation instructions, test those launch
paths before describing them as supported.

------------------------------------------------------------------------

Credits

Mercury Writer was built around the conviction that a serious writing
tool can still be small, understandable, local, and owned by the person
doing the writing.

The manuscript is the product. The software should get out of its way.
