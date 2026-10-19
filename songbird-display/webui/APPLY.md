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

Proxmox serves its UI from a template. Inject the stylesheet once per node and
it themes the whole UI including the login screen. Run on each node:

```bash
TPL=/usr/share/pve-manager/index.html.tpl
cp "$TPL" "$TPL.bak.$(date +%s)"                      # backup
cp proxmox-b42.css /usr/share/pve-manager/css/proxmox-b42.css
# add the <link> once, just before </head>
grep -q proxmox-b42.css "$TPL" || sed -i \
  's#</head>#<link rel="stylesheet" href="/pve2/css/proxmox-b42.css">\n</head>#' "$TPL"
systemctl restart pveproxy
```

Then hard-reload the browser (Ctrl/Cmd-Shift-R).

> A `pve-manager` package upgrade rewrites `index.html.tpl` and drops the line —
> re-run the `sed` step after upgrades (or add it to an APT post-invoke hook).
> To revert: restore the `.bak` file and `systemctl restart pveproxy`.

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
