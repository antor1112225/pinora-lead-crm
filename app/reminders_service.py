"""
Local Desktop Reminders Service for Pinora Lead Workspace + Simple CRM.
Runs 100% locally on Windows. Zero cloud dependencies.
Checks SQLite for overdue and due follow-up reminders.
Dispatches native Windows notifications and updates reminder states.
"""

import sys
import os
import time
import datetime
import subprocess
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import get_connection, get_settings


def send_windows_notification(title: str, message: str):
    """
    Trigger native Windows notification without third-party libraries.
    Uses PowerShell System.Windows.Forms NotifyIcon balloon tip.
    Passes title/message via environment variables to prevent PowerShell command injection.
    """
    ps_exe = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"),
        "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
    )
    if not os.path.exists(ps_exe):
        ps_exe = "powershell"

    ps_script = """
    [void] [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')
    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Icon = [System.Drawing.SystemIcons]::Information
    $notify.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
    $notify.BalloonTipTitle = $env:PINORA_NOTIFY_TITLE
    $notify.BalloonTipText = $env:PINORA_NOTIFY_MSG
    $notify.Visible = $True
    $notify.ShowBalloonTip(7000)
    Start-Sleep -Seconds 1
    $notify.Dispose()
    """

    env = os.environ.copy()
    env["PINORA_NOTIFY_TITLE"] = str(title or "Pinora CRM Reminder")[:120]
    env["PINORA_NOTIFY_MSG"] = str(message or "Follow-up is due.")[:250]

    try:
        subprocess.run(
            [ps_exe, "-NoProfile", "-NonInteractive", "-Command", ps_script],
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            timeout=8
        )
    except Exception as ex:
        # Fallback to simple console notice
        print(f"[REMINDER] {title}: {message} ({ex})")


def check_and_notify_reminders(force_alert: bool = False) -> int:
    """
    Inspect pending reminders due today or overdue.
    Notifies user if not yet notified today.
    Returns count of notified reminders.
    """
    settings = get_settings()
    if settings.get("reminders_enabled", "1") != "1":
        return 0

    conn = get_connection()
    notified_count = 0
    try:
        cur = conn.cursor()
        today_str = datetime.date.today().isoformat()

        # Find pending reminders that haven't been notified yet today
        clause = "" if force_alert else "AND r.notified = 0"
        cur.execute(f"""
            SELECT r.id, r.reminder_date, r.description, l.business_name, l.phone, l.crm_status
            FROM reminders r
            JOIN leads l ON r.lead_id = l.id
            WHERE r.status = 'PENDING'
              AND r.reminder_date <= ?
              AND l.duplicate_status != 'MERGED'
              AND l.crm_status NOT IN ('CLIENT', 'NOT INTERESTED', 'DO NOT CONTACT', 'REPLIED')
              {clause}
        """, (today_str,))
        rows = [dict(r) for r in cur.fetchall()]

        for rem in rows:
            is_overdue = rem["reminder_date"] < today_str
            prefix = "⚠️ OVERDUE" if is_overdue else "⏰ FOLLOW-UP TODAY"
            biz = rem.get("business_name") or "Prospect"
            title = f"{prefix}: {biz}"
            body = f"{rem.get('description') or 'Follow-up is due.'} (Status: {rem.get('crm_status')})"

            send_windows_notification(title, body)

            # Mark reminder notified
            now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cur.execute("UPDATE reminders SET notified = 1, updated_at = ? WHERE id = ?", (now_str, rem["id"]))
            conn.commit()
            notified_count += 1
            time.sleep(1)

        return notified_count
    finally:
        conn.close()


def run_daemon_loop(check_interval_seconds: int = 900):
    """Continuous daemon loop running in the background."""
    print("=" * 60)
    print("  PINORA CRM - BACKGROUND REMINDER SERVICE")
    print(f"  Checking every {check_interval_seconds // 60} minutes for follow-up reminders...")
    print("=" * 60)

    # Save PID file
    pid_file = PROJECT_ROOT / "reminders.pid"
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    try:
        while True:
            try:
                cnt = check_and_notify_reminders()
                if cnt > 0:
                    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Dispatched {cnt} reminder notifications.")
            except Exception as e:
                print(f"[!] Error in reminder check: {e}")
            time.sleep(check_interval_seconds)
    except KeyboardInterrupt:
        print("\nStopping reminder service...")
    finally:
        if pid_file.exists():
            try: pid_file.unlink()
            except Exception: pass


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        run_daemon_loop()
    else:
        cnt = check_and_notify_reminders(force_alert="--test" in sys.argv)
        print(f"Reminder check complete. {cnt} notifications triggered.")
