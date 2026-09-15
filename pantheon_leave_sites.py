#!/usr/bin/env python3
"""
pantheon_leave_sites.py - leave Pantheon site teams you no longer need.

Lists every site where YOU are a team member, ten at a time, lets you tick the
ones to leave, then runs `terminus site:team:remove <site> <you>` for each and
reports what happened.

QUICK START
  1. Get a machine token: Dashboard -> Account -> Machine Tokens -> Create.
     The value is shown ONCE, so copy it right away.
  2. Either paste it into MACHINE_TOKEN below, or (better, keeps it out of
     version control) export it:  export PANTHEON_MACHINE_TOKEN='...'
  3. ./pantheon_leave_sites.py

WHAT TO EXPECT
  Pantheon requires SITE-ADMIN rights to change a site team - including
  removing your own row. If your role on a site is `team_member` or
  `developer`, the API answers "Workflow Creation Failed: Forbidden" and the
  membership stays. This script shows your role per site so you can see it
  coming, and counts those refusals separately at the end. Clearing them needs
  a site admin or someone with support-level access - not a different script.

  Site owners cannot leave their own site team either; those rows show [--]
  and cannot be ticked.

This script only ever touches TEAM MEMBERSHIP for the logged-in user. It runs
no code, deploy, environment or backup commands, and never removes anyone else.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# ===========================================================================
#  CONFIG - edit this block
# ===========================================================================

# Your Pantheon machine token. Leave empty to use the PANTHEON_MACHINE_TOKEN
# environment variable, or whatever session terminus already has.
MACHINE_TOKEN = ""

# Optional: sites to hide from the list entirely, if you already know which ones
# you intend to keep. Left commented out on purpose — most people will just skip
# the ones they want to keep while paging through. Uncomment to use it.
#
# KEEP_SITES = [
#     "my-important-site",
#     "another-site-i-keep",
# ]

# How many sites per page.
PAGE_SIZE = 10

# Path to terminus, and to a php it can run with. Pantheon's terminus needs
# php 8.x; on macOS + Homebrew, php 8.3 lives in the directory below.
TERMINUS = os.environ.get("TERMINUS_BIN") or shutil.which("terminus") or "/usr/local/bin/terminus"
PHP_BIN_DIR = os.environ.get("PHP_BIN_DIR", "/opt/homebrew/opt/php@8.3/bin")

# Look up your role on every site before showing the list. Costs one API call
# per site (run in parallel), and is what tells you which removals can succeed.
FETCH_ROLES = True
ROLE_JOBS = 12

# ===========================================================================
#  End of config
# ===========================================================================

USE_COLOR = sys.stdout.isatty()


def c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


RED = lambda s: c("31", s)      # noqa: E731
GRN = lambda s: c("32", s)      # noqa: E731
YLW = lambda s: c("33", s)      # noqa: E731
DIM = lambda s: c("2", s)       # noqa: E731
BLD = lambda s: c("1", s)       # noqa: E731

# Roles that may edit a site team. Anything else gets Forbidden.
ADMIN_ROLES = {"admin", "owner", "unknown"}


def keep_set() -> set:
    """KEEP_SITES from the config block, or empty when it is commented out."""
    return {s for s in globals().get("KEEP_SITES", []) if s}


def die(msg):
    print(f"{RED('error:')} {msg}", file=sys.stderr)
    sys.exit(1)


def env() -> dict:
    e = os.environ.copy()
    if os.path.isdir(PHP_BIN_DIR):
        e["PATH"] = PHP_BIN_DIR + os.pathsep + e.get("PATH", "")
    return e


def terminus(*args: str) -> subprocess.CompletedProcess:
    """Run terminus, capturing output. Never raises on non-zero exit."""
    return subprocess.run(
        [TERMINUS, *args], capture_output=True, text=True, env=env()
    )


def terminus_json(*args: str):
    proc = terminus(*args, "--format=json")
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip()
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError:
        return None, (proc.stdout or proc.stderr).strip()[:200]


def rows_of(payload) -> list:
    """terminus returns either a dict keyed by id, or a list."""
    if isinstance(payload, dict):
        return list(payload.values())
    return payload or []


# --------------------------------------------------------------------------
#  data gathering
# --------------------------------------------------------------------------

def login_if_token() -> None:
    token = MACHINE_TOKEN or os.environ.get("PANTHEON_MACHINE_TOKEN", "")
    if not token:
        return
    print(DIM("Logging in with machine token..."))
    if terminus("auth:login", f"--machine-token={token}").returncode != 0:
        die("login failed - is that token valid? (tokens are shown once, at creation)")


def whoami() -> tuple:
    data, _ = terminus_json("auth:whoami")
    if not isinstance(data, dict) or not data.get("email"):
        die(
            "not logged in. Put a machine token in MACHINE_TOKEN, export\n"
            "       PANTHEON_MACHINE_TOKEN, or run: terminus auth:login --email=you@example.com"
        )
    return data["email"], data.get("id", "")


def list_team_sites(my_id: str) -> list:
    data, err = terminus_json(
        "site:list", "--team", "--fields=name,id,framework,plan_name,owner,frozen"
    )
    if data is None:
        die(f"site:list failed: {err}")
    keep = keep_set()
    sites = []
    for s in rows_of(data):
        name = s.get("name", "")
        if not name or name in keep:
            continue
        sites.append(
            {
                "name": name,
                "id": s.get("id", ""),
                "framework": s.get("framework") or "-",
                "plan": s.get("plan_name") or "-",
                "frozen": s.get("frozen") in (True, "true", 1),
                "owner": str(s.get("owner", "")).lower() == my_id.lower(),
                "role": "unknown",
                "checked": False,
            }
        )
    sites.sort(key=lambda s: s["name"])
    return sites


def role_on(site_name: str, my_id: str) -> str:
    data, _ = terminus_json("site:team:list", site_name)
    if data is None:
        return "unreadable"
    for m in rows_of(data):
        if str(m.get("id")) == my_id:
            if str(m.get("is_owner", "")).lower() in ("1", "true", "yes"):
                return "owner"
            return m.get("role") or "member"
    return "not-on-team"


def fetch_roles(sites: list, my_id: str) -> None:
    total = len(sites)
    done = 0
    print(f"Checking your role on {total} site(s)...", end="", flush=True)
    with ThreadPoolExecutor(max_workers=ROLE_JOBS) as pool:
        futures = {pool.submit(role_on, s["name"], my_id): s for s in sites}
        for fut, site in futures.items():
            try:
                site["role"] = fut.result()
            except Exception:  # a hiccup on one site must not sink the run
                site["role"] = "unreadable"
            done += 1
            print(f"\r  {done}/{total}", end="", flush=True)
    print(f"\r  {total}/{total} done\n")


# --------------------------------------------------------------------------
#  the checkbox pager
# --------------------------------------------------------------------------

def likely_forbidden(site: dict) -> bool:
    return not site["owner"] and site["role"] not in ADMIN_ROLES


def show_page(sites: list, page: int, pages: int) -> None:
    start = (page - 1) * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(sites))
    ticked = sum(1 for s in sites if s["checked"])
    print()
    print(
        BLD(
            f" Sites {start + 1}-{end} of {len(sites)}   "
            f"(page {page}/{pages})   ticked: {ticked}"
        )
    )
    print(DIM(" " + "-" * 76))
    for i in range(start, end):
        s = sites[i]
        # every box is exactly three visible characters so columns line up
        if s["owner"]:
            box, note = "[-]", DIM(" you own this site")
        elif s["checked"]:
            box, note = f"[{GRN('x')}]", ""
        else:
            box, note = "[ ]", ""
        if not note and likely_forbidden(s):
            note = YLW(" needs admin")
        plan = s["plan"] + (" (frozen)" if s["frozen"] else "")
        print(f" {box} {i + 1:>3}  {s['name']:<42} {s['role']:<12} {plan:<18}{note}")
    print(DIM(" " + "-" * 76))
    print(
        f" {BLD('1 4 7')} or {BLD('1,4,7')} or {BLD('2-6')} tick/untick · "
        f"{BLD('a')} all on page · {BLD('c')} clear page"
    )
    print(
        f" {BLD('Enter')} next page · {BLD('p')} previous · {BLD('g N')} go to page · "
        f"{BLD('r')} run · {BLD('q')} quit"
    )


def toggle(sites: list, token: str) -> None:
    """token is "4" or "2-6" (1-based, inclusive)."""
    try:
        if "-" in token:
            a_s, b_s = token.split("-", 1)
            a, b = int(a_s), int(b_s)
        else:
            a = b = int(token)
    except ValueError:
        print(f"  {YLW('?')} {token!r} is not a number or range")
        return
    for n in range(a, b + 1):
        if not 1 <= n <= len(sites):
            print(f"  {YLW('?')} {n} is outside 1-{len(sites)}")
            continue
        site = sites[n - 1]
        if site["owner"]:
            print(f"  {DIM('- ' + site['name'] + ': you own this site, it cannot be left')}")
            continue
        site["checked"] = not site["checked"]


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "q"


def pager(sites: list) -> bool:
    """Returns True to proceed with removals, False to quit."""
    pages = max(1, (len(sites) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = 1
    while True:
        show_page(sites, page, pages)
        ans = ask("> ")
        low = ans.lower()
        if low in ("", "n"):
            if page < pages:
                page += 1
            else:
                print(DIM("  last page"))
        elif low == "p":
            if page > 1:
                page -= 1
            else:
                print(DIM("  first page"))
        elif low.startswith("g"):
            rest = low[1:].strip()
            if rest.isdigit() and 1 <= int(rest) <= pages:
                page = int(rest)
            else:
                print(f"  {YLW('no such page')} (1-{pages})")
        elif low == "a":
            for s in sites[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
                if not s["owner"]:
                    s["checked"] = True
        elif low == "c":
            for s in sites[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
                s["checked"] = False
        elif low in ("q", "quit"):
            return False
        elif low in ("r", "run"):
            return True
        else:
            for part in ans.replace(",", " ").split():
                toggle(sites, part)


# --------------------------------------------------------------------------
#  removal + stats
# --------------------------------------------------------------------------

def remove_selected(sites: list, me: str, log_path: str, dry_run: bool) -> dict:
    picked = [s for s in sites if s["checked"]]
    stats = {"removed": 0, "forbidden": 0, "other": 0, "failed_names": []}

    print(f"\n{BLD(f'About to leave {len(picked)} site team(s) as {me}:')}")
    for s in picked:
        print(f"  {s['name']:<42} {s['role']}")
    will_fail = sum(1 for s in picked if likely_forbidden(s))
    if will_fail:
        print(
            f"\n{YLW('note:')} {will_fail} of these are roles that cannot edit a site team;\n"
            "      Pantheon will answer Forbidden and leave the membership in place."
        )

    if dry_run:
        print(f"\n{DIM('dry run')} - commands that would run:")
        for s in picked:
            print(f"  terminus site:team:remove {s['name']} {me} -y")
        return stats

    if ask(f"\nType {BLD('REMOVE')} to confirm: ") != "REMOVE":
        print("Aborted. Nothing removed.")
        return stats

    print()
    with open(log_path, "a") as log:
        for s in picked:
            print(f"  {s['name']:<42} ", end="", flush=True)
            proc = terminus("site:team:remove", s["name"], me, "-y")
            out = " ".join((proc.stdout + " " + proc.stderr).split())
            if proc.returncode == 0:
                print(GRN("removed"))
                stats["removed"] += 1
                log.write(f"[ok]   {s['name']}\n")
            else:
                stats["failed_names"].append(s["name"])
                if "Forbidden" in out:
                    print(f"{RED('FAILED')}  Forbidden (needs site admin)")
                    stats["forbidden"] += 1
                else:
                    print(f"{RED('FAILED')}  {out[:120]}")
                    stats["other"] += 1
                log.write(f"[fail] {s['name']} :: {out}\n")
    return stats


def print_stats(sites: list, stats: dict, log_path: str) -> None:
    listed = len(sites)
    ticked = sum(1 for s in sites if s["checked"])
    owned = sum(1 for s in sites if s["owner"])
    failed = stats["forbidden"] + stats["other"]

    print("\n " + "=" * 58)
    print(f" {BLD('RESULTS')}")
    print(f"   listed            {listed}")
    print(f"   ticked            {ticked}")
    print("   " + GRN(f"removed           {stats['removed']}"))
    print("   " + RED(f"failed            {failed}"))
    if stats["forbidden"]:
        print(f"     of which Forbidden (needs site admin)  {stats['forbidden']}")
    if stats["other"]:
        print(f"     of which other errors                  {stats['other']}")
    print(f"   not ticked        {listed - ticked - owned}")
    if owned:
        print(f"   owned by you (cannot leave)  {owned}")
    print(f"   log               {log_path}")
    print(" " + "=" * 58)

    if stats["failed_names"]:
        still = log_path.replace(".log", "-still-a-member.txt")
        with open(still, "w") as fh:
            fh.write("\n".join(stats["failed_names"]) + "\n")
        count = len(stats["failed_names"])
        print("\n" + YLW(f"Still a member of {count} site(s)") + f" - list: {still}")
        print("Those need a site admin (or support-level access) to remove you.")


def main() -> int:
    global PAGE_SIZE, FETCH_ROLES

    ap = argparse.ArgumentParser(
        description="Leave Pantheon site teams, ten at a time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--dry-run", action="store_true", help="show what would run, change nothing")
    ap.add_argument("--no-roles", action="store_true", help="skip the per-site role lookup")
    ap.add_argument("--page-size", type=int, default=PAGE_SIZE, help=f"sites per page (default {PAGE_SIZE})")
    args = ap.parse_args()
    PAGE_SIZE = max(1, args.page_size)
    if args.no_roles:
        FETCH_ROLES = False

    if not os.path.exists(TERMINUS):
        die(f"terminus not found at {TERMINUS} (set TERMINUS_BIN or edit TERMINUS)")

    login_if_token()
    me, my_id = whoami()
    print(f"Logged in as {BLD(me)} ({my_id})")
    print(DIM("Note: this replaced any other terminus session on this machine."))
    print(DIM("      Switch back later with: terminus auth:login --email=<other account>\n"))

    print("Listing sites where you are a team member...")
    sites = list_team_sites(my_id)
    if not sites:
        extra = " outside your KEEP_SITES list" if keep_set() else ""
        print(f"You are not a team member of any site{extra}.")
        return 0

    if FETCH_ROLES:
        fetch_roles(sites, my_id)

    if not pager(sites):
        print("\nNothing removed.")
        return 0
    if not any(s["checked"] for s in sites):
        print("\nNothing ticked, nothing removed.")
        return 0

    log_path = os.path.join(
        os.environ.get("TMPDIR", "/tmp"),
        f"pantheon-leave-sites-{datetime.now():%Y%m%d-%H%M%S}.log",
    )
    stats = remove_selected(sites, me, log_path, args.dry_run)
    if not args.dry_run:
        print_stats(sites, stats, log_path)
    return 1 if (stats["forbidden"] + stats["other"]) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Nothing further was removed.")
        sys.exit(130)
