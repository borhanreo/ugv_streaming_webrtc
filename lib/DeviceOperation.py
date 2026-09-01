from __future__ import annotations

import os

# Env var holding the sudo password for non-interactive contexts (systemd service,
# no TTY). SECURITY NOTE: prefer configuring passwordless sudo (NOPASSWD) for the
# exact commands below instead of a password. If you must use a password, set it
# only in the systemd unit's Environment/EnvironmentFile (outside of git), e.g.:
#   [Service]
#   Environment=UGV_SUDO_PASSWORD=your-password-here
# or better, EnvironmentFile=/etc/ugv/sudo.env (a file with 600 permissions, not
# committed to source control). Never hardcode the password in this file.
_SUDO_PASSWORD_ENV = "UGV_SUDO_PASSWORD"


def _run_with_sudo(command: list[str], *, check: bool = True):
	"""Run `command` prefixed with `sudo`, feeding a password via stdin if
	UGV_SUDO_PASSWORD is set in the environment; otherwise falls back to plain
	`sudo` (works when there's a TTY or passwordless sudo is configured).
	"""

	import subprocess

	password = os.environ.get(_SUDO_PASSWORD_ENV)
	if password:
		# `-S` makes sudo read the password from stdin instead of the TTY/askpass.
		return subprocess.run(
			["sudo", "-S", *command],
			input=password + "\n",
			text=True,
			check=check,
		)
	return subprocess.run(["sudo", *command], check=check)


def device_restart() -> None:
	"""Restart the device by executing the system restart command.

	Notes:
	- Requires passwordless sudo configured, or UGV_SUDO_PASSWORD set in the
	  environment (see module docstring above for the security caveat).
	- On many Linux systems, `reboot` is managed by systemd.
	"""

	import subprocess

	print("Initiating device restart...")
	try:
		_run_with_sudo(["reboot"])
	except subprocess.CalledProcessError as e:
		print(f"Error during restart: {e}")
	except Exception as e:
		print(f"Unexpected error during restart: {e}")


def device_shutdown(*, delay_seconds: int = 0, message: str | None = None) -> None:
    """Shutdown the Raspberry Pi (power off).

    Notes:
    - Requires passwordless sudo configured, or UGV_SUDO_PASSWORD set in the
      environment (see module docstring above for the security caveat).
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
                _run_with_sudo([poweroff_cmd])
            elif shutdown_cmd:
                _run_with_sudo([shutdown_cmd, "-h", "now", msg])
            else:
                _run_with_sudo(["poweroff"])
            return

        minutes = max(1, (delay_seconds + 59) // 60)
        if shutdown_cmd:
            _run_with_sudo([shutdown_cmd, "-h", f"+{minutes}", msg])
        else:
            # Best-effort fallback when shutdown isn't available.
            # Avoid shell=True; just sleep then poweroff.
            sh_cmd = shutil.which("sh") or "/bin/sh"
            _run_with_sudo([sh_cmd, "-c", f"sleep {int(delay_seconds)}; {poweroff_cmd}"])
    except subprocess.CalledProcessError as e:
        print(f"Error during shutdown: {e}")
    except Exception as e:
        print(f"Unexpected error during shutdown: {e}")


def device_service_restart(service_name: str = "acs_ugv.service") -> None:
    """Restart a systemd service (e.g. the UGV app service) via `systemctl restart`.

    Notes:
    - Requires passwordless sudo configured, or UGV_SUDO_PASSWORD set in the
      environment (see module docstring above for the security caveat).
    - Unlike `device_restart`, this only restarts the given service, not the whole device.
    """

    import shutil
    import subprocess

    systemctl_cmd = shutil.which("systemctl") or "/usr/bin/systemctl"

    print(f"Initiating restart of service '{service_name}'...")
    try:
        _run_with_sudo([systemctl_cmd, "restart", service_name])
    except subprocess.CalledProcessError as e:
        print(f"Error during service restart: {e}")
    except Exception as e:
        print(f"Unexpected error during service restart: {e}")
