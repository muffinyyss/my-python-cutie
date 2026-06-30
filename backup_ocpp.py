#!/usr/bin/env python3
"""Backup ocpp folder from Raspberry Pi to local, then clean .log files on the Pi.

Equivalent to:
    scp -r pi@192.168.0.15:~/ocpp "<LOCAL_DIR>"
    ssh pi@192.168.0.15 "rm -f /home/pi/ocpp/*.log"

Just run:  python backup_ocpp.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

# ---- Settings (edit here if needed) ----------------------------------------
PI_USER = "pi"
PI_HOST = "192.168.0.15"
REMOTE_DIR = "~/ocpp"                 # folder on the Pi to download
LOCAL_DIR = r"D:\eds_cream\github\ocpp_backup\Thungtako1"
STATION = "Thungtako1"                           # station name; empty = use the last folder of LOCAL_DIR
CLEAN_LOGS = True                      # remove *.log on the Pi after download

# Zip — only the .zip ends up in LOCAL_DIR (download happens in a temp folder)
MAKE_ZIP = True                        # True = keep only ocpp_<station>.zip in LOCAL_DIR

# ZeroTier
ZT_NETWORK_ID = "9f77fc393ed908e0"                     # <-- put your ZeroTier network ID here (16 hex chars)
ZT_WAIT_SECS = 60                      # how long to wait for the Pi to become reachable
# zerotier-cli path on Windows (default install location). Leave as-is if installed normally.
ZT_CLI = r"C:\ProgramData\ZeroTier\One\zerotier-one_x64.exe"
# ----------------------------------------------------------------------------


def run(cmd):
    """Run a command, streaming output. Returns True on success."""
    print(f"\n>>> {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd)
    except FileNotFoundError:
        print(f"[WARN] Command not found: {cmd[0]}")
        return False
    return result.returncode == 0


def zt_cli():
    """Return a runnable zerotier-cli invocation, or None if not found."""
    # On Windows, prefer the service exe with "-q" — subprocess can't run the
    # zerotier-cli.bat directly, and the exe is what actually works here.
    if os.path.isfile(ZT_CLI):
        return [ZT_CLI, "-q"]
    # Linux/Mac (or if the real cli is on PATH)
    found = shutil.which("zerotier-cli")
    if found:
        return [found]
    return None


def ping_ok(host):
    """Return True if the host answers a single ping (Windows: -n, else -c)."""
    flag = "-n" if os.name == "nt" else "-c"
    return subprocess.run(
        ["ping", flag, "1", host],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def ensure_zerotier():
    """Make sure ZeroTier is up and the Pi is reachable. Returns True if ready."""
    cli = zt_cli()
    if cli is None:
        print("[WARN] zerotier-cli not found. Make sure ZeroTier is installed and running.")
        print(f"       (looked at {ZT_CLI} and on PATH)")
    elif ZT_NETWORK_ID:
        # Try to join (idempotent). Needs admin rights; if it fails we don't
        # care as long as the Pi is reachable (you likely joined already).
        if not run(cli + ["join", ZT_NETWORK_ID]):
            print("[INFO] join skipped/failed (may need admin) — checking reachability anyway.")
    else:
        print("[INFO] ZT_NETWORK_ID is empty — skipping join, will just check reachability.")

    # Wait until the Pi responds (ZeroTier needs a few seconds to come up)
    print(f"\nWaiting for {PI_HOST} to become reachable (up to {ZT_WAIT_SECS}s)...")
    deadline = time.time() + ZT_WAIT_SECS
    while time.time() < deadline:
        if ping_ok(PI_HOST):
            print(f"[OK] {PI_HOST} is reachable.")
            return True
        time.sleep(3)

    print(f"[ERROR] {PI_HOST} is not reachable over the VPN.")
    return False


def main():
    target = f"{PI_USER}@{PI_HOST}"
    start = datetime.now()
    print(f"[{start:%Y-%m-%d %H:%M:%S}] Backing up {target}:{REMOTE_DIR} -> {LOCAL_DIR}")

    # 0) Bring up ZeroTier VPN and make sure the Pi is reachable
    if not ensure_zerotier():
        print("\n[ERROR] VPN/host not ready. Backup aborted, logs were NOT removed.")
        sys.exit(1)

    os.makedirs(LOCAL_DIR, exist_ok=True)
    station = STATION or os.path.basename(LOCAL_DIR.rstrip("\\/"))

    # 1) Download the ocpp folder into a temp dir, so LOCAL_DIR stays clean
    tmp_dir = tempfile.mkdtemp(prefix="ocpp_dl_")
    try:
        if not run(["scp", "-r", f"{target}:{REMOTE_DIR}", tmp_dir]):
            print("\n[ERROR] scp failed. Backup aborted, logs were NOT removed.")
            sys.exit(1)

        print("\n[OK] Download complete.")

        downloaded = os.path.join(tmp_dir, os.path.basename(REMOTE_DIR.rstrip("/")))
        if not os.path.isdir(downloaded):
            print(f"\n[ERROR] Expected folder not found: {downloaded}")
            sys.exit(1)

        # 1b) Zip into LOCAL_DIR (only the .zip lands there)
        if MAKE_ZIP:
            zip_base = os.path.join(LOCAL_DIR, f"ocpp_{station}")
            print(f"\nZipping -> {zip_base}.zip")
            zip_path = shutil.make_archive(zip_base, "zip", root_dir=downloaded)
            size_mb = os.path.getsize(zip_path) / (1024 * 1024)
            print(f"[OK] Created {zip_path} ({size_mb:.1f} MB)")
        else:
            # No zip: place the plain folder in LOCAL_DIR as ocpp_<station>
            dest = os.path.join(LOCAL_DIR, f"ocpp_{station}")
            shutil.rmtree(dest, ignore_errors=True)
            shutil.move(downloaded, dest)
            print(f"[OK] Saved folder {dest}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 2) On the Pi: delete .log files, but only empty out MDBlog.txt (keep the file)
    if CLEAN_LOGS:
        remote_cmd = (
            "rm -f /home/pi/ocpp/*.log; "
            "truncate -s 0 /home/pi/ocpp/MDBlog.txt"
        )
        if run(["ssh", target, remote_cmd]):
            print("[OK] Remote .log files removed and MDBlog.txt cleared.")
        else:
            print("[WARN] Could not clean remote .log / MDBlog.txt files.")

    elapsed = (datetime.now() - start).total_seconds()
    print("\n" + "=" * 50)
    print(f"  Backup สำเร็จ! ใช้เวลา {elapsed:.1f} วินาที")
    if MAKE_ZIP:
        print(f"  ไฟล์: {os.path.join(LOCAL_DIR, f'ocpp_{station}.zip')}")
    print("=" * 50)


if __name__ == "__main__":
    main()
