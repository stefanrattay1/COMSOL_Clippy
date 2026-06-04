<div align="center">

<h1>COMSOL Clippy 📎</h1>

<p><strong>Ask Claude questions about your COMSOL manuals and get answers with the exact manual and page number.</strong></p>

<p>
   <img alt="Works with Claude Desktop or Claude Code" src="https://img.shields.io/badge/Claude-Desktop%20or%20Code-D97706?style=flat-square">
   <img alt="Manuals live in source folder" src="https://img.shields.io/badge/Manuals-source%2F-0F766E?style=flat-square">
   <img alt="Runs on Windows Linux and WSL" src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20WSL-1D4ED8?style=flat-square">
   <img alt="One time setup" src="https://img.shields.io/badge/Setup-Run%20start.cmd-111827?style=flat-square">
</p>

<p><em>Set it up once. After that, you just chat with Claude.</em></p>

</div>

---

## At a glance ✨

| You do | COMSOL Clippy does |
| --- | --- |
| Put COMSOL PDF manuals into **`source`** | Finds and prepares them for search |
| Run **`start.cmd`** once | Sets up the local helper automatically |
| Ask Claude a COMSOL question | Answers with the manual and page number |

---

## What you need first 🧰

1. **The manuals.** Put your COMSOL files into the folder named **`source`** 📂
   (it's right here next to this file). Some are already there — you can add more
   anytime. **PDF** manuals work best (with page numbers); you can also drop in plain
   **notes** as `.txt` or `.md` files. Scanned/photo PDFs without selectable text and
   Word `.docx` won't work — export those to PDF first.
2. **Claude installed** on your computer (Claude Desktop or Claude Code). If you can
   already chat with Claude, you're good.

That's it. You do **not** need to install Python or anything else by hand — the setup
does it for you.

---

## Step-by-step setup (do this once)

### On Windows 🪟

1. Open the folder that contains this file.
2. Find the file called **`start.cmd`**.
3. **Double-click it.**
4. A black window opens and text scrolls by. **Leave it alone** and wait. The first
   time it has a lot to download and prepare, so it can take **10–30 minutes**. ☕
5. When it says **“Done”**, you can close the window.

> If Windows shows a blue “Windows protected your PC” box, click **More info → Run
> anyway**. (This just means the file isn't signed; it's safe — it's the file in this
> folder.)

### On Linux / WSL 🐧

1. Open a terminal in this folder.
2. Type this and press Enter:
   ```
   bash start.cmd
   ```
3. Wait for it to finish (first time: **10–30 minutes**). When it says **“Done”**,
   you're set.

---

## Step 2: Restart Claude 🔄

After setup says “Done”, **fully close Claude and open it again.** (On Windows,
right-click the Claude icon near the clock and choose Quit, then reopen it.) This lets
Claude see the new helper.

---

## Step 3: Ask a question 🎉

Open a **new chat** with Claude and ask anything about COMSOL. Some examples to try:

- **How do I set up conjugate heat transfer in COMSOL?**
- **Which turbulence model should I use for internal pipe flow?**
- **How do I add a temperature-dependent material property?**
- **Why won't my nonisothermal flow model converge?**
- **What does the Application Builder let me do?**

Not sure what's available? Just ask: **“What manuals can you search?”** — Claude will
list every document it has indexed.

Claude will look inside your manuals and answer, showing where it found the
information, like this:

> *…see [HeatTransferModuleUsersGuide.pdf p.412].*

(For notes you added as `.txt`/`.md`, citations look like `[notes.md #3]` — the chunk
number, since text files have no pages.)

You can ask follow-up questions normally. Done!

---

## Adding or changing manuals later ➕

1. Put new PDFs into the **`source`** folder (or replace/remove old ones).
2. Run the setup again (double-click **`start.cmd`**, or `bash start.cmd`).

It's smart: it only processes what changed, so it's quick the second time. Then restart
Claude.

---

## Something not working? 🛠️

- **Claude doesn't seem to know about the manuals.** Make sure you fully **quit and
  reopened** Claude after setup (not just closed the window).
- **It said “No source documents found”.** Your files need to be **PDF** (or `.txt`/
  `.md`) files directly inside the **`source`** folder — not in a sub-folder.
- **One file was “SKIPPED”.** That PDF is likely password-protected or a scanned image
  with no selectable text. The other files still work; remove or replace the skipped one.
- **The setup window showed an error.** Run `start.cmd` once more — it picks up where
  it left off.
- **Want a quick health check?** The setup ends with a self-check that confirms the
  helper is working and prints a sample answer. If you ever want to re-run just that
  check, open this folder in a terminal and run:
  `.venv/bin/python main.py status` (Windows: `.venv-win\Scripts\python main.py status`).
  It should end with **“all checks passed.”**
- Still stuck? See the technical notes in **[docs/TECHNICAL.md](docs/TECHNICAL.md)**.

---

*Curious how it works under the hood? See **[docs/TECHNICAL.md](docs/TECHNICAL.md)**.*
