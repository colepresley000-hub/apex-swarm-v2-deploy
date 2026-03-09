#!/usr/bin/env python3
"""
PATCH: Daemon Auto-Start on Railway Boot
========================================
Adds a startup routine to main.py that:
1. Auto-starts all 6 preset daemons when the app boots
2. Skips any already-running daemons (idempotent)
3. Logs each daemon start to Railway logs
4. Adds a /api/v1/daemons/status endpoint for health verification

Usage:
  python3 patch_daemon_autostart.py
  git add -A && git commit -m "feat: auto-start all daemons on Railway boot" && railway up
"""

import re

MAIN_FILE = "main.py"

# ── 1. AUTO-START FUNCTION ──────────────────────────────────────────────────
# Injected right before the app startup event or at end of init block

AUTOSTART_FUNCTION = '''
# ── DAEMON AUTO-START ────────────────────────────────────────────────────────
BOOT_DAEMONS = [
    "crypto-monitor",
    "defi-yield-scanner",
    "news-sentinel",
    "whale-watcher",
    "competitor-tracker",
    "competitor-intel",
]

async def autostart_daemons():
    """Auto-start all preset daemons on boot. Idempotent — skips running ones."""
    print("[BOOT] Starting daemon auto-start sequence...", flush=True)
    started = 0
    skipped = 0
    failed = 0
    for preset_id in BOOT_DAEMONS:
        try:
            # Check if already running
            already_running = any(
                d.get("preset_id") == preset_id and d.get("status") == "running"
                for d in daemon_manager.daemons.values()
            ) if hasattr(daemon_manager, "daemons") else False

            if already_running:
                print(f"[BOOT] Daemon '{preset_id}' already running — skipped", flush=True)
                skipped += 1
                continue

            # Find preset config
            preset = next((p for p in DAEMON_PRESETS if p["id"] == preset_id), None)
            if not preset:
                print(f"[BOOT] WARNING: No preset found for '{preset_id}'", flush=True)
                failed += 1
                continue

            # Start the daemon
            daemon_id = await daemon_manager.start_daemon(
                agent_type=preset["agent_type"],
                task_description=preset["task"],
                interval_seconds=preset["interval_seconds"],
                preset_id=preset_id,
            )
            print(f"[BOOT] ✅ Started '{preset_id}' → daemon_id={daemon_id} (every {preset['interval_seconds']}s)", flush=True)
            started += 1

        except Exception as e:
            print(f"[BOOT] ❌ Failed to start '{preset_id}': {e}", flush=True)
            failed += 1

    print(f"[BOOT] Daemon auto-start complete: {started} started, {skipped} skipped, {failed} failed", flush=True)
'''

# ── 2. STARTUP EVENT HOOK ────────────────────────────────────────────────────
# Appended inside the existing @app.on_event("startup") or added fresh

STARTUP_HOOK = '''
@app.on_event("startup")
async def startup_autostart_daemons():
    """Boot hook: auto-start all preset daemons."""
    try:
        await autostart_daemons()
    except Exception as e:
        print(f"[BOOT] Auto-start error (non-fatal): {e}", flush=True)
'''

# ── 3. STATUS ENDPOINT ───────────────────────────────────────────────────────

STATUS_ENDPOINT = '''
@app.get("/api/v1/daemons/status")
async def get_daemon_status(api_key: str = Depends(verify_api_key)):
    """
    Returns live status of all daemons.
    Shows: id, preset_id, status, last_run, next_run, run_count, last_error
    """
    try:
        daemons = daemon_manager.daemons if hasattr(daemon_manager, "daemons") else {}
        now = datetime.utcnow()

        result = []
        for daemon_id, d in daemons.items():
            interval = d.get("interval_seconds", 0)
            last_run = d.get("last_run")
            next_run = None
            if last_run and interval:
                try:
                    lr = datetime.fromisoformat(last_run) if isinstance(last_run, str) else last_run
                    next_run = (lr + timedelta(seconds=interval)).isoformat()
                except Exception:
                    pass

            result.append({
                "daemon_id": daemon_id,
                "preset_id": d.get("preset_id", "custom"),
                "agent_type": d.get("agent_type"),
                "status": d.get("status", "unknown"),
                "interval_seconds": interval,
                "run_count": d.get("run_count", 0),
                "last_run": last_run,
                "next_run_estimated": next_run,
                "last_error": d.get("last_error"),
            })

        # Flag any boot daemons that are missing entirely
        running_presets = {r["preset_id"] for r in result}
        missing = [p for p in BOOT_DAEMONS if p not in running_presets]

        return {
            "total_daemons": len(result),
            "running": sum(1 for r in result if r["status"] == "running"),
            "stopped": sum(1 for r in result if r["status"] != "running"),
            "missing_boot_daemons": missing,
            "daemons": result,
            "checked_at": now.isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")
'''

# ── PATCH LOGIC ──────────────────────────────────────────────────────────────

def patch():
    with open(MAIN_FILE, "r") as f:
        content = f.read()

    original = content
    changes = []

    # 1. Inject AUTOSTART_FUNCTION before the first @app.on_event or @app.get("/")
    if "async def autostart_daemons" in content:
        print("⏭  autostart_daemons() already present — skipping function injection")
    else:
        # Insert before first route definition
        insert_before = '@app.get("/")'
        if insert_before in content:
            content = content.replace(insert_before, AUTOSTART_FUNCTION + "\n\n" + insert_before, 1)
            changes.append("✅ Injected autostart_daemons() function")
        else:
            print("⚠️  Could not find insertion point for autostart_daemons() — appending at end")
            content += "\n" + AUTOSTART_FUNCTION
            changes.append("✅ Appended autostart_daemons() function (end of file)")

    # 2. Add startup hook (only if no existing startup event calls autostart)
    if "startup_autostart_daemons" in content:
        print("⏭  startup_autostart_daemons already present — skipping hook")
    else:
        # Try to append after existing startup event if present
        startup_match = re.search(r'(@app\.on_event\("startup"\)[^\n]*\nasync def \w+\(\)[^}]+?(?=\n@|\Z))', content, re.DOTALL)
        if startup_match:
            insert_pos = startup_match.end()
            content = content[:insert_pos] + "\n\n" + STARTUP_HOOK + content[insert_pos:]
            changes.append("✅ Added startup_autostart_daemons hook after existing startup event")
        else:
            # No existing startup event — inject before first route
            insert_before = '@app.get("/")'
            if insert_before in content:
                content = content.replace(insert_before, STARTUP_HOOK + "\n\n" + insert_before, 1)
                changes.append("✅ Added startup_autostart_daemons hook before first route")

    # 3. Add status endpoint
    if "get_daemon_status" in content:
        print("⏭  /api/v1/daemons/status already present — skipping endpoint")
    else:
        # Inject before the closing of daemon routes block, or before first get("/")
        if '@app.get("/api/v1/daemons"' in content:
            insert_before = '@app.get("/api/v1/daemons"'
            content = content.replace(insert_before, STATUS_ENDPOINT + "\n\n" + insert_before, 1)
            changes.append("✅ Added /api/v1/daemons/status endpoint")
        else:
            content += "\n" + STATUS_ENDPOINT
            changes.append("✅ Appended /api/v1/daemons/status endpoint (end of file)")

    if content == original:
        print("\n⚠️  No changes made — patch may already be applied.")
        return

    with open(MAIN_FILE, "w") as f:
        f.write(content)

    print("\n" + "="*50)
    print("PATCH APPLIED SUCCESSFULLY")
    print("="*50)
    for c in changes:
        print(c)
    print(f"\nTotal changes: {len(changes)}")
    print("\nNext steps:")
    print("  git add -A && git commit -m 'feat: auto-start all daemons on boot + /daemons/status endpoint' && railway up")

if __name__ == "__main__":
    patch()
