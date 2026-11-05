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

## Stage B — cutover

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
