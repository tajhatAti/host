# Pre-installed system tools (RunSpace)

Every RunSpace job runs in a container that already has these command-line
tools. Call them from your code with `subprocess` (Python) or `child_process`
(Node) — there is **no install step**, and nothing to request per job.

| Tool | Commands | Typical use |
|---|---|---|
| **ffmpeg** | `ffmpeg`, `ffprobe` | trim/convert audio and video, read media metadata |
| **imagemagick** | `convert`, `mogrify`, `identify` | resize, crop, convert images |
| **git** | `git` | clone repos (also powers the GitHub-import button) |
| **zip / unzip** | `zip`, `unzip`, `tar`, `xz` | build and extract archives |
| **curl / wget** | `curl`, `wget` | fetch files over HTTP |
| **sqlite3** | `sqlite3` | inspect a bot's database from the terminal |
| **jq** | `jq` | slice JSON in shell pipelines |

Language runtimes also present: Python 3.11, Node 20, Ruby, PHP, Perl, Lua,
Java 17, Go, Rust.

## Example — trimming audio in a Telegram bot

```python
import subprocess

# How long is the file?
dur = subprocess.run(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
     "-of", "default=noprint_wrappers=1:nokey=1", "input.mp3"],
    capture_output=True, text=True, check=True,
).stdout.strip()

# First 30 seconds, no re-encode.
subprocess.run(
    ["ffmpeg", "-y", "-i", "input.mp3", "-t", "30", "-c", "copy", "out.mp3"],
    check=True,
)
```

Two things worth knowing:

- **Write inside your job's own folder.** Files you create next to `main.py`
  survive restarts and redeploys — see the data-backup section on the job's
  Details page. Files written to `/tmp` do not.
- **`check=True` turns a failed command into an exception**, which shows up in
  your logs. Without it a broken `ffmpeg` call fails silently and the bot just
  looks stuck.

## Why you cannot run `apt-get install`

RunSpace is a shared, free, multi-tenant platform: one container serves many
people's bots. If any job could install system packages at runtime, one user
could change — or break — the environment everyone else's bots depend on. It
is also an obvious abuse vector on a service with anonymous signup.

So system packages are installed **once, at image build time**, under platform
control. Your job code cannot install them, and it does not need to: the tools
above are already on `PATH`.

This does **not** limit your language libraries. `pip` and `npm` packages are
installed per job, automatically, from your imports or a `requirements.txt` /
`package.json` — that is isolated to your own workspace and stays supported.

## Need a tool that is not listed?

Ask, and it gets reviewed and added to the base image — message the CodeNest
Telegram channel with the tool name and what you are building. Adding one is a
small change; what will not be added is a mechanism for jobs to install
arbitrary packages themselves.

---

### Maintainer notes

The list is defined in **two** places and they must stay in lockstep, or the
single-service and two-service deployments quietly become different platforms:

- `Dockerfile` — the default single-service image
- `runner/Dockerfile` — the standalone runner used in the two-service layout

Both keep the media tooling in its own `RUN` layer, so adding a tool later
does not rebuild the whole toolchain above it. `tests/test_system_tools.py`
asserts the two files agree and that nothing introduces a runtime `apt-get`.

After changing either file, **redeploy both Render services** — a Dockerfile
edit only takes effect on a rebuild.
