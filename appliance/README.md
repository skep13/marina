# lab3 portable AI appliance

Turn lab3 into a standalone box you plug any device into over ethernet: the
device gets an IP automatically, finds the box at **http://ai.local**, and
reaches the web chat and the model API with zero setup. lab3 runs everything
locally — the model (ct110 `marina-brain`: llama-swap `:8080` + Marina bridge
`:8765`) and the chat (ct100 `marina-chat-lab3`, Open WebUI). Marina and
Songbird are both served.

Everything is driven by [`setup-lab3.sh`](setup-lab3.sh), run on the lab3
Proxmox host as root. It has two stages.

## Stage A — reversible (done)

`setup-lab3.sh stage-a` installs and configures, changing nothing about your
LAN:

- Clones Open WebUI onto lab3 as ct100 (done separately, by snapshot/restore
  from lab1 ct112, so all connections/users/theming came over).
- Installs **Caddy** (reverse proxy), **avahi** (mDNS → `ai.local`), and
  **dnsmasq** (DHCP) — dnsmasq staged **off** so it can't fight your LAN.
- Caddy serves, on port 80 for host `ai.local`:
  - `/` → the web chat (ct100)
  - `/v1/*` → the model API (ct110 llama-swap), with the API key **injected by
    the proxy**, so plugged-in apps need no key on the isolated network.
  - `/install` → a device bootstrap stub.

Test it now, while lab3 is still on your LAN (send the appliance hostname):

```bash
curl -H 'Host: ai.local' http://192.168.1.13/v1/models
curl -H 'Host: ai.local' -X POST http://192.168.1.13/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"marina","messages":[{"role":"user","content":"hi"}]}'
```

(Verified: chat page, `/v1/models`, and a live `marina` completion all work
keyless through the proxy.)

## Wi-Fi access (no cable) — recommended

Instead of (or as well as) the wired cutover, lab3 can host **its own Wi-Fi**:
devices join the network and open `http://ai.local`, with the wired port left
on your LAN so the box stays manageable. The Intel AX200 does AP mode on
2.4 GHz for roughly 8 devices.

```bash
printf 'YOUR_WPA2_PASSPHRASE' > /etc/appliance/ap.pass && chmod 600 /etc/appliance/ap.pass
/root/setup-lab3.sh wifi-ap      # SSID is AP_SSID in the script
```

This installs/configures hostapd (SSID from `AP_SSID`), gives the Wi-Fi NIC
`10.42.0.1`, and serves DHCP + `ai.local` on it via dnsmasq — the same Caddy
proxy already answers chat + the keyless API. Verified: a client gets a
`10.42.0.x` lease, resolves `ai.local`, and both the chat and `/v1` serve.
The passphrase lives only in `/etc/appliance/ap.pass` and `hostapd.conf` on the
box, never in the repo.

### Keeping internet while you use the box

A laptop has one Wi-Fi radio, so joining "Local AI Box" used to mean losing
the internet. Two ways round it:

- **Box cabled to a router (home, office):** lab3's wired port stays on that
  LAN, so the laptop stays on its normal Wi-Fi and reaches Marina over the LAN
  (`http://192.168.1.15:8765`, or `http://<lab3-ip>/marina/` with
  `Host: ai.local`). Nothing to join.
- **Joining the box's Wi-Fi:** `wifi-ap` now also NATs Wi-Fi clients out of
  the wired port (`share-internet`), and dnsmasq forwards other names upstream,
  so a laptop on "Local AI Box" keeps the internet whenever the box itself is
  cabled to a router. With no cable anywhere, tether the laptop to a phone
  over USB and put that service above Wi-Fi in the macOS network order.

Marina's bridge is proxied at `http://ai.local/marina/` (health, chat/stream),
so apps on the box's Wi-Fi need only that one address.

### Hosting and joining at once (`wifi-both`)

With no cable anywhere, lab3's Wi-Fi card can do both jobs: host "Local AI
Box" and join another network (your phone's hotspot, a café's Wi-Fi) for
internet, which it shares with everyone on "Local AI Box". The AP moves to a
virtual interface (`wlap0`); the card itself joins the uplink.

Limits of the hardware: both have to be on **one 2.4 GHz channel**. A watcher
moves "Local AI Box" onto the uplink's channel, so its clients drop for a few
seconds whenever that happens. On an iPhone hotspot turn on **Maximise
Compatibility** (otherwise it's 5 GHz only). Don't list your home Wi-Fi here:
it shares `192.168.1.x` with the wired port; at home, use the cable.

1. On the box, list the networks to join (the passwords stay on the box).
   The name has to match exactly, spaces included: an iPhone's hotspot is
   often called `iPhone (2)`, not `iPhone(2)`. Keep the iPhone's Personal
   Hotspot screen open while the box first joins; it stops advertising soon
   after you leave it.

   ```bash
   cat > /etc/appliance/uplink.conf <<'EOF'
   network={
       ssid="My iPhone"
       psk="hotspot password"
   }
   EOF
   ```

2. Run it detached (your connection to "Local AI Box" drops while it switches):

   ```bash
   systemd-run --unit=appliance-wifi-both /root/setup-lab3.sh wifi-both
   ```

3. Rejoin "Local AI Box", check you have internet, then keep it:

   ```bash
   ssh root@10.42.0.1 /root/setup-lab3.sh wifi-both-ok
   ```

   If you can't get back on within 10 minutes, it reverts to plain AP mode on
   its own (`WIFI_REVERT_WINDOW`). If the AP doesn't come up at all it reverts
   straight away. `setup-lab3.sh status` shows the channel, the uplink and the
   route; `setup-lab3.sh wifi-ap-only` turns it off.

All the tools it needs (`wpasupplicant`, `isc-dhcp-client`, `hostapd`, `iw`)
must already be installed; with no uplink yet there's no `apt`, so it checks
first and changes nothing if one is missing. When the cable is plugged in, the
box prefers it for internet automatically.

### Calling Marina from a phone (`phone`)

Marina's own app, with hands-free calls, for phones on "Local AI Box". It is
served over HTTPS on port 8443, because browsers only let a page use the
microphone over HTTPS, and only to devices on the box's Wi-Fi.

1. Copy the app into ct110 under `/opt/marina/app/`: `app/renderer`,
   `app/models/model.vrm` and `app/build/icon.png` from the repo.
2. On lab3: `/root/setup-lab3.sh phone`. This makes a token for the proxy
   (`/etc/appliance/phone.token`, never in the repo) and turns on `web:` in her
   config with that token. Her bridge still refuses everything else from the
   network. It restarts her bridge and Caddy, and publishes the box's
   certificate.
3. On the phone, once: join "Local AI Box", open
   `http://10.42.0.1/marina-ca.crt` and trust it.
   - **iPhone:** Settings › Profile Downloaded › Install, then Settings ›
     General › About › Certificate Trust Settings › turn it on.
   - **Android:** Settings › Security › Encryption & credentials › Install a
     certificate › CA certificate.
4. Open **https://10.42.0.1:8443** (or `https://ai.local:8443`), Share › Add
   to Home Screen, and tap the green phone button to call her.

### Moving the box around (`roam`)

For a box that gets plugged in somewhere different each time. Your laptop
stays on its own Wi-Fi the whole time. Run it once:

```bash
/root/setup-lab3.sh roam
```

- **Plugged into a Mac:** turn on Internet Sharing on the Mac (System Settings ›
  General › Sharing › Internet Sharing, from Wi-Fi to the USB ethernet
  adapter). The box takes an address from the Mac and uses its internet, and
  Marina and the chat are at **http://ai.local**. Without Internet Sharing the
  box still answers at `http://169.254.42.1`. For that, leave the Mac's ethernet
  on "Using DHCP": macOS then picks a `169.254.x` address on the cable by itself.
- **Plugged into a router:** the box takes an address there and uses its
  internet. At home it keeps `192.168.1.13` as well.
- **Nothing on the cable:** the box uses its Wi-Fi uplink (`wifi-both`) if
  one's in range, and "Local AI Box" works as always.

The containers go out through lab3 (lab3 is their gateway and DNS), so Marina
keeps her internet (Telegram, web tools) wherever the box has some. mDNS
answers `ai.local` on each network with the box's address there.

Marina's bridge and the keyless model API answer only from trusted networks
(`TRUSTED_NETS`): "Local AI Box", the cable (`169.254.x`, or a Mac's Internet
Sharing on `192.168.2-3.x`), the home LAN and Tailscale. On anyone else's
network, other devices get a 403.

### From any network (Tailscale)

With the box at home and cabled to the router, you can reach it from anywhere
over Tailscale and keep your normal internet:

```bash
/root/setup-lab3.sh tailscale    # installs Tailscale, joins as "lab3"; open the login link it prints
```

Then sign in to the same Tailscale account on your laptop. The box answers at
`http://lab3` (chat), `http://lab3/v1` (keyless API) and `http://lab3/marina/`
(Marina's bridge; the café game finds it automatically). This needs MagicDNS,
which Tailscale turns on by default; otherwise use the box's `100.x` address.

## Stage B — cutover (only if you want the WIRED port to be the appliance net)

This repurposes the wired NIC into the appliance network. **It cuts lab3 off
your LAN and ends the SSH session.** You can do it two ways.

### Remotely, no display (recommended — lab3 is headless)

`cutover --remote` arms an **auto-rollback** before it changes anything: if you
don't confirm within a window (default 600s), it restores the LAN config and
SSH comes back — so a botched cutover can't lock you out. Run it detached so it
survives your SSH dropping:

```bash
# on lab3, over SSH (after leaving the cluster, below):
systemd-run --unit=appliance-cutover /root/setup-lab3.sh cutover --remote
```

Your SSH will freeze/drop within a second — that's expected. Then:
1. Plug a laptop into lab3's wired port. It gets a `10.42.0.x` address.
2. Open **http://ai.local** — if the chat loads, it worked.
3. Make it permanent: `ssh root@10.42.0.1 '/root/setup-lab3.sh confirm'`.
4. If anything went wrong, do nothing — in ~10 min it reverts to the LAN and you
   can SSH back to `192.168.1.13` to retry. Tune the window with
   `ROLLBACK_WINDOW=900 systemd-run ... cutover --remote`.

### At the console (if you have a keyboard+screen)

```bash
/root/setup-lab3.sh cutover      # type CUTOVER to confirm; no rollback needed
```

Either way the cutover re-addresses `vmbr0` to `10.42.0.1/24`, moves
ct110→`10.42.0.10` and ct100→`10.42.0.11`, re-points the proxy and WebUI at the
new model IP, and turns on DHCP (`10.42.0.50–200`) + mDNS.

### First: leave the Proxmox cluster

lab3 is a cluster node, so make it standalone before the cutover. From another
node (e.g. lab1): `pvecm delnode lab3`. Then on lab3:

```bash
systemctl stop pve-cluster corosync
pmxcfs -l
rm -f /etc/corosync/* /etc/pve/corosync.conf
killall pmxcfs; systemctl start pve-cluster
```

### Optional: wifi uplink
lab3 has wifi (`wls1`). To give the appliance its own internet (updates, web
tools, model downloads) connect it to a network — e.g. with NetworkManager or
`wpa_supplicant` + `dhclient wls1`. Leave `vmbr0` as the local appliance net.

## The device side
Chat needs nothing but a browser. For the Marina/Songbird **agent**, point its
base URL at `http://ai.local/v1` (no key) — `curl http://ai.local/install`
prints the details. The agent UI lives in `server/agent/` (built separately).

## Settings
All addresses/IDs are variables at the top of `setup-lab3.sh`
(`APPLIANCE_IP`, `DHCP_*`, `WEBUI_CTID`, `MODEL_CTID`, …). `setup-lab3.sh
status` shows what's configured and running.
