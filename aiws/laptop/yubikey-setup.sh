#!/usr/bin/env bash
# YubiKey on the laptop: plug the key in and the lock screen unlocks; Enter at the
# greeter/lock logs in with no tap; sudo + polkit take a tap. Password still works.
# Also the same SSH key + lab aliases as the Mac, and lab3.home trusted for Proxmox WebAuthn.
# Run from the Mac: aiws/laptop/yubikey-setup.sh   (needs aiws/tools/laptop to reach it)
# Then on the laptop, with the key plugged in, enroll it (touch when it blinks):
#   pamu2fcfg -P -u "$USER" -o pam://cachyos-x8664 -i pam://cachyos-x8664 | sudo tee /etc/u2f_mappings
# (-P: enroll without "+presence", otherwise pam_u2f demands a tap even with userpresence=0)
set -euo pipefail
cd "$(dirname "$0")/../.."
L=aiws/tools/laptop

$L root 'pacman -S --needed --noconfirm pam-u2f libfido2 yubikey-manager ccid && systemctl enable --now pcscd.socket'

# PAM: key is "sufficient" before the password; nouserok keeps password login
# working until the key is enrolled. Not added to system-auth, so SSH is unaffected.
$L root '
LINE="auth       sufficient   pam_u2f.so authfile=/etc/u2f_mappings origin=pam://cachyos-x8664 appid=pam://cachyos-x8664 cue [cue_prompt=Touch your YubiKey] nouserok"
[ -f /etc/pam.d/polkit-1 ] || cp /usr/lib/pam.d/polkit-1 /etc/pam.d/polkit-1
[ -f /etc/u2f_mappings ] || install -m644 /dev/null /etc/u2f_mappings
for f in greetd login sudo polkit-1; do
  p=/etc/pam.d/$f; grep -q pam_u2f "$p" && continue
  cp "$p" "$p.bak-yubikey"
  case $f in sudo|polkit-1) up=1;; *) up=0;; esac
  awk -v l="$LINE userpresence=$up" "!done && /^[[:space:]]*-?auth[[:space:]]+(include|substack|required[[:space:]]+pam_unix|sufficient|\[)/ {print l; done=1} {print}" "$p.bak-yubikey" > "$p"
done'

# Plug-in unlock: udev -> yubikey-unlock.service -> proves the enrolled key via the
# yubikey-unlock PAM service (no tap) -> loginctl unlock-session (Noctalia obeys logind).
$L push aiws/laptop/yubikey/ /tmp/ykunlock/
$L root 'cd /tmp/ykunlock
install -Dm755 yubikey-unlock.py /usr/local/libexec/yubikey-unlock
install -m644 yubikey-unlock.pam /etc/pam.d/yubikey-unlock
install -m644 yubikey-unlock.service /etc/systemd/system/yubikey-unlock.service
install -m644 70-yubikey-unlock.rules /etc/udev/rules.d/70-yubikey-unlock.rules
systemctl daemon-reload && udevadm control --reload'

# SSH: the resident-key handle from the Mac (useless without the YubiKey) + lab aliases.
$L push ~/.ssh/id_ed25519_sk ~/.ssh/id_ed25519_sk.pub /home/friereon/.ssh/
$L run 'cd ~/.ssh && chmod 600 id_ed25519_sk && grep -q "^Host lab1 lab2 lab3" config 2>/dev/null || cat >> config <<EOF
# YubiKey 5C (touch to log in)
Host lab1
  HostName 192.168.1.10
Host lab2
  HostName 192.168.1.11
Host lab3
  HostName 192.168.1.13
Host lab1 lab2 lab3 192.168.1.10 192.168.1.11 192.168.1.13
  User root
  IdentityFile ~/.ssh/id_ed25519_sk
EOF
chmod 600 config; grep -qF "$(cat id_ed25519_sk.pub)" authorized_keys || cat id_ed25519_sk.pub >> authorized_keys'

# Proxmox WebAuthn needs https://lab3.home:8006 with the Mac's mkcert CA trusted
# (public cert only; Arch's nss uses p11-kit, so Firefox picks it up too).
$L push "$(mkcert -CAROOT)/rootCA.pem" /tmp/mkcert-rootCA.pem
$L root 'install -m644 /tmp/mkcert-rootCA.pem /etc/ca-certificates/trust-source/anchors/mkcert-mac-rootCA.crt && trust extract-compat
grep -q lab3.home /etc/hosts || echo "192.168.1.13 lab3.home" >> /etc/hosts'
