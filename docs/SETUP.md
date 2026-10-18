# Install Terminus

Terminus runs as two small processes: a private organism core and a transparent desktop body. Each computer gets its own creature. The public memory bank and automatic source updates are separate options, both off until enabled.

You need Git, Python 3.10 or newer, and [uv](https://docs.astral.sh/uv/getting-started/installation/). Install into your own writable folder, outside a network share or a cloud-synced folder. Keep the `.local` folder when moving or updating an installation.

## Windows 10 or 11

Use a normal PowerShell window in the desktop account that will own Terminus. If Git and Python are not already installed:

```powershell
winget install --id Git.Git --exact --source winget
winget install --id Python.Python.3.12 --exact --source winget
```

Open a new PowerShell window after those installations, then:

```powershell
py -m pip install --user uv
cd $HOME\Documents
git clone https://github.com/Esemianczuk/Terminus.git
cd Terminus
py -m uv run python scripts/setup.py
```

The body uses Qt's Direct3D 11 renderer. Setup registers `core`, `desktop` and `presence` tasks under `\Terminus\` in Task Scheduler. They use the current user's interactive login, without storing a password or running as administrator. This matters: a GUI started directly from an SSH shell runs in a different session and will not appear on your desktop. The installer can be run through SSH as the same user if that user is already signed into the desktop.

**Bring Back Terminus.lnk** appears on your actual Desktop, including a redirected Desktop. The guardian runs every minute. Core and desktop jobs also restart after failures. The shortcut starts the jobs, clears deliberate pauses and moves him to the lower right. Explicit Quit remains respected until a deliberate start or recovery.

Windows observation uses read-only pointer and window geometry queries. It does not hook the keyboard, read key states, identify what you type, inspect window titles or record sound. Typing rhythm and background color sampling are not implemented on Windows yet. Gaze, animation, procedural skin, ASCII and ink rendering work there; camouflage uses its procedural palette without sampled desktop colors.

Logs are `.local\windows-core.log`, `.local\windows-desktop.log` and `.local\windows-presence.log`. Task Manager should show the desktop process in your interactive session, not Session 0. Private files inherit the access controls of your Windows user folder; keep the checkout out of shared writable directories.

## macOS

Install [Git](https://git-scm.com/download/mac) and [uv](https://docs.astral.sh/uv/getting-started/installation/). With Homebrew already installed, `brew install git uv` supplies both. uv can provide Python if needed.

```sh
cd ~/Documents
git clone https://github.com/Esemianczuk/Terminus.git
cd Terminus
uv run python scripts/setup.py
```

Run this while signed into the graphical desktop. Setup creates per-user launch agents, a nonactivating Metal window and **Bring Back Terminus.app**. No system daemon is installed. The resident body cannot appear at the login screen.

Window geometry and pointer awareness work without reading text. Typing rhythm requires macOS Input Monitoring access. Use the creature's explicit permission menu command if you want it. Background color matching is a separate option that needs Screen Recording permission. Neither permission is required to run him or share category learning. Logs live in `.local/macos-*.log`.

## Linux

Use a graphical session with a systemd user manager. Install Git with your distribution's package manager and [uv](https://docs.astral.sh/uv/getting-started/installation/).

On Ubuntu, Qt's X11 libraries may also be needed:

```sh
sudo apt install git libegl1 libopengl0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxkbcommon-x11-0
```

Then, without sudo:

```sh
cd ~/Documents
git clone https://github.com/Esemianczuk/Terminus.git
cd Terminus
uv run python scripts/setup.py
```

Setup installs systemd user services, an XDG login entry, a recovery timer and **Bring Back Terminus.desktop**. Some desktop environments ask you to allow launching that shortcut once. The tested native renderer uses OpenGL. X11 supports desktop geometry, aggregate input rhythm and optional background colors. Wayland support depends on the compositor's overlay policy; cross-application awareness is unavailable there.

```sh
journalctl --user -u terminus-core -u terminus-desktop -f
```

## Check, stop and recover

From the checkout on any OS:

```sh
uv run python scripts/servicectl.py status
uv run python scripts/servicectl.py stop --part desktop
uv run python scripts/servicectl.py start
uv run python scripts/bring_back.py
```

On Windows, use `py -m uv` wherever these examples say `uv` if uv is not on PATH. A body-only stop leaves the private core running. `servicectl.py disable` disables login startup and the presence guardian. Recovery only manages tasks belonging to this checkout; it never kills another application's processes.

## Updates from GitHub

For a manual update:

```sh
uv run python scripts/update.py
```

For hourly automatic checks:

```sh
uv run python scripts/update.py --enable-auto
uv run python scripts/update.py --status
```

Disable them with `--disable-auto`. Each computer fetches GitHub independently. Updates follow `main`, require a clean checkout and a fast-forward, and never discard local commits or source edits. A SQLite backup is made before rebuilding. Bank-only and documentation-only changes advance the checkout without restarting the creature. Source changes rebuild and restore the installed services while preserving intentional pauses. A failed rebuild remains pending for a later retry; details are in `.local/update-status.json` and the OS job log.

The jobs are `terminus-updates.timer` on Linux, `org.terminus.updates` on macOS and `\Terminus\updates` on Windows. They need outbound HTTPS to GitHub and the Python package sources. They do not open an inbound port or wake a sleeping computer. Installing new code automatically means trusting this repository's maintainers; leave it off if you prefer reviewing updates yourself.

## Optional shared memory

Enable independent local learning and public-bank downloads:

```sh
uv run python scripts/collective.py enable
uv run python scripts/collective.py sync
uv run python scripts/collective.py status
```

No GitHub account or token is needed to read the bank. The scheduler exchanges about every ten minutes while the computer is awake and its user services can run. Offline operation uses the newest validated cached round. The desktop API stays on `127.0.0.1:8769`; do not expose that port to connect creatures.

Publishing is a separate choice. A GitHub account with write access to the repository can install [GitHub CLI](https://cli.github.com/), run `gh auth login` on that machine, then enable publishing:

```sh
uv run python scripts/collective.py enable --publish
```

Other users can submit a validated outbox JSON from `.local/collective-outbox/` in a pull request under `community/contributions/`. Public does not mean anonymous write access. No shared write credential comes with the project.

For several personal machines, one trusted publisher can relay the other learners' numerical packets. Configure SSH key access and verify the peers' host keys first. Run these on the publisher, using your actual aliases and checkout paths:

```sh
uv run python scripts/collective.py enable --publish --peer-ssh my-mac --peer-root /Users/me/Documents/Terminus
uv run python scripts/collective.py enable --publish --peer-ssh my-windows --peer-root 'C:\Users\Me\Documents\Terminus' --peer-platform win32
```

Adding a peer preserves the existing peers. Enable ordinary collective learning on each peer too. Windows SSH must support PowerShell and the same user's checkout. The publisher retrieves only schema-validated numerical contributions; it never retrieves another creature's database, token, contexts or private model. `.local/collective-relay-status.json` records successful and deferred peers. A disconnected peer does not block the others.

Across different networks, public-bank reads and direct GitHub publishing use HTTPS and need no LAN. An SSH relay needs a route to its peers, such as a trusted VPN or private mesh. Otherwise contributions wait locally until that route returns; neither SSH nor a home network is made publicly reachable by this setup.

Disable exchange with `uv run python scripts/collective.py disable`. This stops exchange at the configuration gate and preserves the creature's ordinary local memory. See [the exact public format and its limits](COLLECTIVE_MEMORY.md).
