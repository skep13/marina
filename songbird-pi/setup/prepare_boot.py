#!/usr/bin/env python3
# ====================================================================
#  Songbird Pi - prepare a freshly written Raspberry Pi OS (Trixie) disk
#
#  Run on the Mac after writing the image to an SD card or USB stick,
#  with its boot partition mounted:
#
#      python3 songbird-pi/setup/prepare_boot.py /Volumes/bootfs
#
#  Writes cloud-init first-boot config: host songbird-pi, user skep
#  (SSH key only, auto-login on the HDMI console, no password), Wi-Fi
#  (hotspot, home, college - read from the pet's gitignored config), I2C
#  on at 400 kHz, and the OLED readout service. The Wi-Fi passwords are
#  scrubbed from the boot partition after the first boot.
# ====================================================================
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PET_CONFIG = os.path.join(REPO, "songbird-pet", "firmware", "main", "songbird_config.h")
OLED_DIR = os.path.join(REPO, "songbird-pi", "oled")
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519.pub")

USER_DATA = """#cloud-config
# Songbird Pi: terminal-only, SSH key login, OLED readout on I2C.
hostname: songbird-pi
timezone: Europe/London
keyboard:
  model: pc105
  layout: gb

# One user, no password: SSH with the Mac's key, auto-login on the HDMI
# console. Set a password later with `sudo passwd skep` if you want one.
users:
  - name: skep
    gecos: skep
    groups: [sudo, adm, video, plugdev]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: true
    ssh_authorized_keys:
      - {key}
ssh_pwauth: false

# wait for Pi OS's own first-boot apt run instead of failing on its lock
apt:
  conf: |
    DPkg::Lock::Timeout "300";
packages:
  - i2c-tools
  - python3-pyte          # the OLED's keyboard terminal

write_files:
  - path: /etc/modules-load.d/i2c-dev.conf
    content: |
      i2c-dev
  - path: /etc/default/console-setup
    content: |
      ACTIVE_CONSOLES="/dev/tty[1-6]"
      CHARMAP="UTF-8"
      CODESET="guess"
      FONTFACE="TerminusBold"
      FONTSIZE="16x32"
      VIDEOMODE=
  - path: /etc/profile.d/songbird.sh
    content: |
      [ -n "$PS1" ] && printf '\\n  \\033[33m*\\033[0m  SONGBIRD PI   %s   %s\\n\\n' "$(hostname -I | cut -d' ' -f1)" "$(date '+%a %d %b %H:%M')"

runcmd:
  - [ sh, -c, "usermod -aG i2c,gpio skep || true" ]
  - [ install, -m, "0755", /boot/firmware/songbird/songbird_oled.py, /usr/local/bin/songbird_oled.py ]
  - [ install, -m, "0755", /boot/firmware/songbird/oled_terminal.py, /usr/local/bin/oled_terminal.py ]
  - [ install, -m, "0644", /boot/firmware/songbird/songbird-oled.service, /etc/systemd/system/songbird-oled.service ]
  # front panel: shell hook for running/finished commands, the `oled` command
  - [ install, -m, "0644", /boot/firmware/songbird/songbird-oled.tmpfiles, /etc/tmpfiles.d/songbird-oled.conf ]
  - [ systemd-tmpfiles, --create, /etc/tmpfiles.d/songbird-oled.conf ]
  - [ install, -m, "0644", /boot/firmware/songbird/songbird-jobs.sh, /etc/profile.d/songbird-jobs.sh ]
  - [ install, -m, "0755", /boot/firmware/songbird/oled, /usr/local/bin/oled ]
  - [ modprobe, i2c-dev ]
  - [ systemctl, daemon-reload ]
  - [ systemctl, enable, --now, songbird-oled.service ]
  - [ systemctl, enable, --now, ssh ]
  - [ sh, -c, "setupcon --force || true" ]
  # console auto-login: done here, not in write_files - Pi OS's own first
  # boot clears getty drop-ins written earlier
  - [ mkdir, -p, /etc/systemd/system/getty@tty1.service.d ]
  - [ sh, -c, "printf '[Service]\\nExecStart=\\nExecStart=-/sbin/agetty --autologin skep --noclear %%I $TERM\\n' > /etc/systemd/system/getty@tty1.service.d/autologin.conf" ]
  - [ sh, -c, "systemctl daemon-reload && systemctl restart getty@tty1" ]
  - [ sh, -c, "sed -i 's/password: .*/password: \\"(removed after first boot)\\"/' /boot/firmware/network-config" ]
"""

NETWORK_HEAD = """# Songbird Pi Wi-Fi: phone hotspot, home, college. Applied once on first
# boot; the passwords below are scrubbed from this file afterwards.
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
      optional: true
  wifis:
    wlan0:
      dhcp4: true
      optional: true
      regulatory-domain: GB
      access-points:
"""

CONFIG_TXT = """
# Songbird: OLED on I2C bus 1 (pins 3/5), fast mode for smooth animation
dtparam=i2c_arm=on
dtparam=i2c_arm_baudrate=400000
"""


def networks():
    cfg = open(PET_CONFIG).read()

    def d(k):
        m = re.search(r'#define %s\s+"([^"]*)"' % k, cfg)
        return m.group(1) if m else ""

    pairs = [(d("PET_WIFI_SSID"), d("PET_WIFI_PASS")),
             (d("PET_WIFI2_SSID"), d("PET_WIFI2_PASS")),
             (d("PET_WIFI3_SSID"), d("PET_WIFI3_PASS"))]
    return [(s, p) for s, p in pairs if s]


def main():
    boot = sys.argv[1] if len(sys.argv) > 1 else "/Volumes/bootfs"
    if not os.path.exists(os.path.join(boot, "user-data")):
        sys.exit(f"{boot} doesn't look like a Raspberry Pi OS (Trixie) boot partition")

    key = open(SSH_KEY).read().strip()
    with open(os.path.join(boot, "user-data"), "w") as f:
        f.write(USER_DATA.replace("{key}", key))

    aps = "".join("        %s:\n          password: %s\n" % (json.dumps(s), json.dumps(p))
                  for s, p in networks())
    with open(os.path.join(boot, "network-config"), "w") as f:
        f.write(NETWORK_HEAD + aps)

    cfg_path = os.path.join(boot, "config.txt")
    cfg = open(cfg_path).read()
    if not re.search(r"^dtparam=i2c_arm=on", cfg, re.M):
        with open(cfg_path, "a") as f:
            f.write(CONFIG_TXT)

    dest = os.path.join(boot, "songbird")
    os.makedirs(dest, exist_ok=True)
    for name in ("songbird_oled.py", "oled_terminal.py", "songbird-oled.service", "songbird-oled.tmpfiles",
                 "songbird-jobs.sh", "oled"):
        shutil.copy(os.path.join(OLED_DIR, name), dest)

    print("prepared", boot, "- networks:", [s for s, _ in networks()])


if __name__ == "__main__":
    main()
