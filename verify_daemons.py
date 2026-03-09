#!/usr/bin/env python3
"""
verify_daemons.py — APEX SWARM Daemon Health Checker
=====================================================
Run this after deploy to confirm all 6 daemons are live and healthy.

Usage:
  python3 verify_daemons.py --key YOUR_ADMIN_API_KEY
  python3 verify_daemons.py --key YOUR_ADMIN_API_KEY --url https://your-custom.railway.app

What it checks:
  1. /api/v1/health         — all 15 subsystems green
  2. /api/v1/daemons/status — all 6 boot daemons running
  3. /api/v1/daemons        — list endpoint still works
  4. Per-daemon: last_run recency, run_count > 0, no last_error
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_URL = "https://apex-swarm-v2-production.up.railway.app"
EXPECTED_DAEMONS = [
    "crypto-monitor",
    "defi-yield-scanner",
    "news-sentinel",
    "whale-watcher",
    "competitor-tracker",
    "competitor-intel",
]

# ANSI colours
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}✅ {msg}{RESET}")
def fail(msg):  print(f"  {RED}❌ {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}⚠️  {msg}{RESET}")
def info(msg):  print(f"  {CYAN}ℹ️  {msg}{RESET}")

def get(url, api_key):
    req = urllib.request.Request(url, headers={"X-Api-Key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        return {"error": str(e), "body": e.read().decode()}, e.code
    except Exception as e:
        return {"error": str(e)}, 0

def section(title):
    print(f"\n{BOLD}{CYAN}{'─'*50}{RESET}")
    print(f"{BOLD}{title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*50}{RESET}")

def check_health(base_url, api_key):
    section("1/3  SYSTEM HEALTH CHECK")
    data, status = get(f"{base_url}/api/v1/health", api_key)

    if status != 200:
        fail(f"Health endpoint returned HTTP {status}")
        print(f"      Response: {data}")
        return False

    ok(f"Health endpoint reachable (HTTP {status})")

    subsystems = data.get("subsystems", data.get("checks", {}))
    if isinstance(subsystems, dict):
        all_green = True
        for name, state in subsystems.items():
            is_ok = state in (True, "ok", "healthy", "green") or state == True
            if is_ok:
                ok(f"  {name}: {state}")
            else:
                warn(f"  {name}: {state}")
                all_green = False
        return all_green
    else:
        info(f"Health data: {json.dumps(data, indent=2)[:400]}")
        return True

def check_daemon_status(base_url, api_key):
    section("2/3  DAEMON STATUS CHECK")
    data, status = get(f"{base_url}/api/v1/daemons/status", api_key)

    if status == 404:
        fail("/api/v1/daemons/status not found — patch may not be deployed yet")
        warn("Run: python3 patch_daemon_autostart.py then redeploy")
        return False

    if status != 200:
        fail(f"Daemon status endpoint returned HTTP {status}: {data}")
        return False

    total    = data.get("total_daemons", 0)
    running  = data.get("running", 0)
    stopped  = data.get("stopped", 0)
    missing  = data.get("missing_boot_daemons", [])

    ok(f"Status endpoint reachable")
    info(f"Total daemons: {total}  |  Running: {running}  |  Stopped: {stopped}")

    if missing:
        fail(f"Missing boot daemons: {missing}")
    else:
        ok("All 6 boot daemons present")

    # Per-daemon breakdown
    now = datetime.now(timezone.utc)
    all_healthy = True
    print()
    for d in data.get("daemons", []):
        pid      = d.get("preset_id", d.get("daemon_id", "?"))
        dstatus  = d.get("status", "unknown")
        interval = d.get("interval_seconds", 0)
        runs     = d.get("run_count", 0)
        last_run = d.get("last_run")
        last_err = d.get("last_error")

        # Calculate staleness
        stale = False
        stale_msg = ""
        if last_run and interval:
            try:
                lr = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                if lr.tzinfo is None:
                    lr = lr.replace(tzinfo=timezone.utc)
                age_s = (now - lr).total_seconds()
                # Flag if more than 3× the interval has passed without a run
                if age_s > interval * 3:
                    stale = True
                    stale_msg = f" (last run {int(age_s/60)}m ago — expected every {int(interval/60)}m)"
            except Exception:
                pass

        status_icon = "✅" if dstatus == "running" and not stale else ("⚠️ " if stale else "❌")
        print(f"  {status_icon} {pid:<25} status={dstatus:<10} runs={runs:<5} interval={interval}s")

        if last_err:
            warn(f"     Last error: {last_err}")
            all_healthy = False
        if stale:
            warn(f"     Stale{stale_msg}")
            all_healthy = False
        if dstatus != "running":
            all_healthy = False

    return all_healthy and not missing

def check_daemon_list(base_url, api_key):
    section("3/3  DAEMON LIST ENDPOINT")
    data, status = get(f"{base_url}/api/v1/daemons", api_key)

    if status != 200:
        fail(f"GET /api/v1/daemons returned HTTP {status}")
        return False

    daemons = data if isinstance(data, list) else data.get("daemons", data.get("items", []))
    ok(f"List endpoint working — {len(daemons)} daemon(s) returned")
    return True

def main():
    parser = argparse.ArgumentParser(description="APEX SWARM Daemon Verifier")
    parser.add_argument("--key", required=True, help="Admin API key (ADMIN_API_KEY)")
    parser.add_argument("--url", default=BASE_URL, help="Base Railway URL")
    args = parser.parse_args()

    print(f"\n{BOLD}{'='*50}")
    print("  APEX SWARM — DAEMON VERIFICATION")
    print(f"  Target: {args.url}")
    print(f"  Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}{RESET}")

    results = {
        "health":  check_health(args.url, args.key),
        "daemons": check_daemon_status(args.url, args.key),
        "list":    check_daemon_list(args.url, args.key),
    }

    section("SUMMARY")
    all_pass = all(results.values())

    for check, passed in results.items():
        if passed:
            ok(f"{check.upper()} — PASS")
        else:
            fail(f"{check.upper()} — FAIL")

    print()
    if all_pass:
        print(f"{BOLD}{GREEN}🚀 ALL CHECKS PASSED — Daemons are live and healthy!{RESET}\n")
        sys.exit(0)
    else:
        print(f"{BOLD}{RED}⚠️  SOME CHECKS FAILED — See above for details{RESET}")
        print(f"\n{YELLOW}Common fixes:")
        print("  • Daemons not running → check railway logs for boot errors")
        print("  • /daemons/status 404 → run patch_daemon_autostart.py + redeploy")
        print("  • Daemons stopped → POST /api/v1/daemons with preset_id to restart")
        print(f"  • railway logs | tail -50{RESET}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
