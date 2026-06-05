from __future__ import annotations


def device_restart() -> None:
	"""Restart the device by executing the system restart command.

	Notes:
	- This typically requires running as root or having passwordless sudo configured.
	- On many Linux systems, `reboot` is managed by systemd.
	"""

	import subprocess

	print("Initiating device restart...")
	try:
		subprocess.run(["/usr/bin/sudo", "reboot"], check=True)
	except subprocess.CalledProcessError as e:
		print(f"Error during restart: {e}")
	except Exception as e:
		print(f"Unexpected error during restart: {e}")
def device_shutdown(*, delay_seconds: int = 0, message: str | None = None) -> None:
    """Shutdown the Raspberry Pi (power off).

    Notes:
    - Requires running as root or having passwordless sudo for shutdown/poweroff.
    - Uses systemd when available, otherwise falls back to the `shutdown` command.
    """
    import shutil
    import subprocess
    import sys

    if sys.platform.startswith("win"):
        print("Shutdown requested, but this platform is Windows; ignoring.")
        return

    if delay_seconds < 0:
        raise ValueError("delay_seconds must be >= 0")

    msg = (message or "UGV remote shutdown").strip() or "UGV remote shutdown"
    print(f"Initiating device shutdown (delay_seconds={delay_seconds})...")

    poweroff_cmd = shutil.which("poweroff") or "poweroff"
    shutdown_cmd = shutil.which("shutdown")

    try:
        if delay_seconds == 0:
            if poweroff_cmd:
                subprocess.run(["sudo", poweroff_cmd], check=True)
            elif shutdown_cmd:
                subprocess.run(["sudo", shutdown_cmd, "-h", "now", msg], check=True)
            else:
                subprocess.run(["sudo", "poweroff"], check=True)
            return

        minutes = max(1, (delay_seconds + 59) // 60)
        if shutdown_cmd:
            subprocess.run(["sudo", shutdown_cmd, "-h", f"+{minutes}", msg], check=True)
        else:
            # Best-effort fallback when shutdown isn't available.
            # Avoid shell=True; just sleep then poweroff.
            sh_cmd = shutil.which("sh") or "/bin/sh"
            subprocess.run(["sudo", sh_cmd, "-c", f"sleep {int(delay_seconds)}; {poweroff_cmd}"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error during shutdown: {e}")
    except Exception as e:
        print(f"Unexpected error during shutdown: {e}")
