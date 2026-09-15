# Pantheon Leave Sites

[![Status](https://img.shields.io/badge/status-working-22C55E.svg)](#status)
[![Python](https://img.shields.io/badge/Python-3.8+-3776AB.svg)](https://www.python.org)
[![Terminus](https://img.shields.io/badge/Terminus-3.x_|_4.x-FFDC28.svg)](https://docs.pantheon.io/terminus)
[![Dependencies](https://img.shields.io/badge/dependencies-none-lightgrey.svg)](#requirements)

A single-file interactive tool for leaving Pantheon site teams you no longer need to be on.

Support and consulting work adds you to customer site teams constantly, and nothing ever takes you
back off. After a year or two the dashboard lists a hundred sites you have no business seeing. This
script lists every site where you are a team member, ten at a time, lets you tick the ones to leave,
and runs `terminus site:team:remove` for each — reporting exactly what Pantheon did with every one.

There is no dependency to install, no config file and no framework: one Python file, the standard
library, and a `terminus` binary you already have.

## Status

Working, and honest about its limits — which are Pantheon's, not the script's.

**Read this before you plan a big cleanup:** Pantheon requires **site-admin rights to modify a site
team, including removing your own row**. If your role on a site is `team_member` or `developer`, the
API answers

```
[error]  Workflow Creation Failed: Forbidden
```

and your membership stays exactly where it was. This is not a bug, a scope problem with your token,
or something a different command works around. Things that were tried and do not help:

- **A second, more privileged account.** An account that can *see* a site through an organization is
  not on its team and cannot edit it either.
- **The user-side membership endpoint** (`/api/users/<uid>/memberships/sites/<site>`), which the
  dashboard appears to use. It rejects `DELETE` with `501 I don't know how to treat a DELETE request`.
  There is no "leave site" API.

So on a typical consultant account, a minority of memberships come off with this tool and the rest
need a site admin, or someone with support-level access, to remove you. The script is built around
that reality rather than hiding it: it looks up your role on every site up front, marks the
hopeless ones `needs admin` **before** you tick anything, and counts `Forbidden` separately from
real errors in the summary. Nothing is ambiguous at the end — you get a list of the sites you are
still a member of, written to a file.

Site owners cannot leave their own site team either. Those rows render `[-]` and cannot be ticked.

## Requirements

- **Python 3.8 or newer** — standard library only, nothing to `pip install`
- **Terminus 3.x or 4.x**, authenticated (see [Installing Terminus](#installing-terminus))
- **PHP 8.x** on `PATH`, because Terminus itself is PHP

### Installing Python

Check first — you very likely have it:

```bash
python3 --version
```

If that prints `3.8` or higher, skip ahead.

**macOS.** Python 3 ships with the Command Line Tools. If `python3` is missing, either of these
gets you there:

```bash
xcode-select --install          # Apple's toolchain, includes python3
brew install python             # or Homebrew, if you prefer to manage it yourself
```

**Debian / Ubuntu:**

```bash
sudo apt update && sudo apt install -y python3
```

**RHEL / Fedora / Amazon Linux:**

```bash
sudo dnf install -y python3
```

**Windows.** Install from [python.org/downloads](https://www.python.org/downloads/) and **tick "Add
python.exe to PATH"** in the installer. Then use `py` instead of `./`:

```powershell
py pantheon_leave_sites.py
```

### Installing Terminus

Follow [Pantheon's install guide](https://docs.pantheon.io/terminus/install). On macOS with
Homebrew:

```bash
brew install pantheon-systems/external/terminus
```

Terminus runs on PHP 8.x. If you keep several PHP versions around, put the right one first on
`PATH` for the session:

```bash
export PATH="/opt/homebrew/opt/php@8.3/bin:$PATH"   # macOS + Homebrew
```

The script also prepends `PHP_BIN_DIR` (see [Configuration](#configuration)) so it can find PHP
without you exporting anything.

## Installation

Download the one file, make it executable, and you are done:

```bash
curl -O https://raw.githubusercontent.com/jraborar/pantheon-leave-sites/main/pantheon_leave_sites.py
chmod +x pantheon_leave_sites.py
./pantheon_leave_sites.py --help
```

Or clone the repository:

```bash
git clone https://github.com/jraborar/pantheon-leave-sites.git
cd pantheon-leave-sites
chmod +x pantheon_leave_sites.py
```

`chmod +x` is what lets you run it as `./pantheon_leave_sites.py`. Skip it if you would rather
always type `python3 pantheon_leave_sites.py`, which works regardless.

## Authentication

The script uses whatever session Terminus already has. To check:

```bash
terminus auth:whoami
```

If that is already the account you want to clean up, run the script and nothing else is needed.

Otherwise you need a **machine token**, because Pantheon does not let you retrieve an existing
token's value — the list in your dashboard shows names and IDs only. Create a new one:

**Dashboard → Account → Machine Tokens → Create token.** The value is shown **once**, so copy it
immediately. Creating a token does not revoke any existing token.

Then either export it (keeps it out of the file, and out of version control):

```bash
export PANTHEON_MACHINE_TOKEN='your-token-here'
./pantheon_leave_sites.py
```

or paste it into `MACHINE_TOKEN` at the top of the script.

> **Logging in with a token replaces the active Terminus session on that machine.** If you share
> the machine with a service account or run other Pantheon tooling locally, switch back afterwards
> with `terminus auth:login --email=<the other account>`. Tokens already stored on the machine are
> reused by email, so you do not need that token's value again.

## Usage

```bash
./pantheon_leave_sites.py --dry-run     # look, change nothing
./pantheon_leave_sites.py               # the real thing
```

The script lists your team memberships, checks your role on each (one API call per site, run in
parallel), then pages through them:

```
 Sites 1-10 of 25   (page 1/3)   ticked: 2
 ----------------------------------------------------------------------------
 [x]   1  admin-site                       admin        Elite
 [-]   2  my-own-site                      owner        Sandbox          you own this site
 [x]   3  site-01                          team_member  Basic            needs admin
 [ ]   4  site-02                          team_member  Basic            needs admin
 [ ]   5  site-03                          admin        Basic
 ----------------------------------------------------------------------------
 1 4 7 or 1,4,7 or 2-6 tick/untick · a all on page · c clear page
 Enter next page · p previous · g N go to page · r run · q quit
```

| Input | Effect |
|---|---|
| `3` | tick/untick site 3 |
| `1 4 7` or `1,4,7` | tick/untick several |
| `2-6` | tick/untick a range |
| `a` | tick everything on this page |
| `c` | clear everything on this page |
| `Enter` or `n` | next page |
| `p` | previous page |
| `g 3` | jump to page 3 |
| `r` | run the removals |
| `q` | quit, changing nothing |

Ticks persist across pages, so you can work through the whole list and then run once. `r` shows
what is about to happen, warns how many of your picks will hit the admin wall, and requires you to
type `REMOVE` before anything is sent.

### Options

| Flag | Purpose |
|---|---|
| `--dry-run` | print the `terminus` commands that would run, change nothing |
| `--no-roles` | skip the per-site role lookup — faster start, but no `needs admin` warnings |
| `--page-size N` | show N sites per page instead of 10 |

### Results

Every removal prints as it happens, then a summary:

```
 ==========================================================
 RESULTS
   listed            25
   ticked            14
   removed           2
   failed            12
     of which Forbidden (needs site admin)  11
     of which other errors                  1
   not ticked        10
   owned by you (cannot leave)  1
   log               /tmp/pantheon-leave-sites-20260915-173342.log
 ==========================================================

Still a member of 12 site(s) - list: …-still-a-member.txt
```

`Forbidden` is counted apart from other errors because the two mean different things: the first is
the permission wall described in [Status](#status), the second is something worth reading the log
about. The log records every command's full output, and the `-still-a-member.txt` file lists the
sites that did not come off, ready to hand to whoever can remove you.

Exit code is `0` when everything ticked came off (or you quit without running), `1` if anything
failed — so it composes into a larger script.

## Configuration

The block at the top of the file is the whole configuration surface:

| Setting | Default | Notes |
|---|---|---|
| `MACHINE_TOKEN` | `""` | Prefer the `PANTHEON_MACHINE_TOKEN` environment variable |
| `KEEP_SITES` | commented out | Optional. Uncomment to hide sites you know you are keeping |
| `PAGE_SIZE` | `10` | Sites per page |
| `TERMINUS` | auto-detected | Override with the `TERMINUS_BIN` environment variable |
| `PHP_BIN_DIR` | `/opt/homebrew/opt/php@8.3/bin` | Prepended to `PATH` so Terminus finds a PHP 8 |
| `FETCH_ROLES` | `True` | The role lookup that produces the `needs admin` warnings |
| `ROLE_JOBS` | `12` | Parallel workers for that lookup |

`KEEP_SITES` ships commented out deliberately: most people would rather see the full list and skip
what they keep, and nobody should inherit someone else's keep-list.

## What it does and does not touch

It calls exactly three Terminus commands: `site:list --team` and `site:team:list` to read, and
`site:team:remove <site> <you>` to write. It only ever passes **your own** address, so it cannot
remove a colleague. It runs no code, deploy, environment, database or backup operation, and it does
not touch organization memberships — leaving a site team is unrelated to the orgs you belong to, and
if your access to a site comes through an organization, removing the team row will not revoke it.

A refused removal changes nothing. There is no partial state to clean up.

## Troubleshooting

**`error: not logged in`** — no session and no token. See [Authentication](#authentication).

**`error: terminus not found`** — set `TERMINUS_BIN=/path/to/terminus`, or edit `TERMINUS` in the
config block.

**`no php on PATH`** — Terminus needs PHP 8.x. Set `PHP_BIN_DIR` to the right bin directory, or put
it on `PATH` yourself.

**`Workflow Creation Failed: Forbidden`** — expected on any site where you are not an admin. See
[Status](#status).

**`login failed`** — machine tokens are shown once, at creation. An old token you cannot read from
the dashboard cannot be recovered; create a new one.

**Every row shows role `unknown`** — you passed `--no-roles`, so nothing was looked up.
