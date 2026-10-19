# Applying the retro-futurist themes

Four self-contained CSS files, each with its background image embedded as a
data URI — no asset hosting, no extra files to copy. You only ever paste one
`<style>` block.

| File | Target | Look |
|------|--------|------|
| `proxmox-b42.css` | Proxmox VE UI on **lab1, lab2, lab3** | brutalist black/white + iridescent, B42 wallpaper |
| `owui-reze.css`   | **Open WebUI** (Songbird) | Reze — black / hot-pink / teal |
| `owui-daisy.css`  | a custom-CSS container | violet / rose / teal, daisy art |
| `owui-crimson.css`| a custom-CSS container | steel + crimson, silver art |

Regenerate any of them after swapping an image in `assets/`:
`python3 gen_prox.py` (Proxmox) or `python3 gen_owui.py` (containers).

---

## Proxmox (lab1 / lab2 / lab3)

These nodes already run a managed **uplink** theme: `/usr/local/sbin/uplink-pve-theme`
(re-run after apt via `/etc/apt/apt.conf.d/99-uplink-pve-theme`) builds
`/pve2/css/uplink.css` from `/usr/local/share/uplink-pve/uplink.css` plus an
optional per-host layer `uplink-host.css`, and injects a version-fingerprinted
`<link>` into `index.html.tpl`. A standalone `<link>` of our own gets covered by
uplink's own `body::before` wallpaper and reset on upgrade, so we ride uplink's
per-host layer instead — it's concatenated after uplink.css (so it overrides),
fingerprinted (so browsers refetch), and re-applied on every upgrade.

`uplink-host-b42.css` is that layer: it re-points uplink's `--ul-*` variables and
`body::before` wallpaper to the B42 look. On each node:

```bash
# generate from the image first:  python3 gen_uplink_host.py
install -m 0644 uplink-host-b42.css /usr/local/share/uplink-pve/uplink-host.css
/usr/local/sbin/uplink-pve-theme          # rebuilds uplink.css, bumps ?v=, reloads pveproxy
```

A node without uplink (lab3 was one) first needs the infra cloned from a themed
node: `/usr/local/sbin/uplink-pve-theme`, `/usr/local/share/uplink-pve/`
(`uplink.css`, `uplink.js`, `uplink-bg.svg`) and `/etc/apt/apt.conf.d/99-uplink-pve-theme`.

Then hard-reload the browser (Ctrl/Cmd-Shift-R).

> To revert: `rm /usr/local/share/uplink-pve/uplink-host.css` and re-run
> `uplink-pve-theme` (restores plain uplink). `proxmox-b42.css` / `gen_prox.py`
> remain for a node that has **no** uplink theme — link it directly in that case.

## Open WebUI + other custom-CSS containers

Drop the matching file into whatever custom-CSS slot the container already uses.
For a standard Open WebUI build, inject before `</head>` in the served
`index.html` (path varies by image, commonly `/app/build/index.html`):

```bash
# inside the container, adjust the path to your build
IDX=/app/build/index.html
cp "$IDX" "$IDX.bak"
printf '<link rel="stylesheet" href="/owui-reze.css">\n' # or serve inline
```

If your container theming already works by pasting CSS, just paste the file's
contents — nothing else is needed.

---

Prefer I apply these for you? Authorize this key on the hosts and I'll connect
and do all of the above live, then tune the Proxmox CSS against the real DOM:

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJxJ5LUz5KYGnYil/cS1DK4Le/rgQy0DBIDGmJFnxHTi jacobmatthews@jacobs-macbook-air.tail35b6c6.ts.net
```
