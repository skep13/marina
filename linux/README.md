# Marina for Linux

Marina on the Mint laptop (lab2): her whole body in a window, with her idle
animation, lip sync, expressions, and full-body animations for what she does in
*asterisks*. It's the Mac app's renderer (`app/renderer`) and model
(`app/models/model.vrm`), so she looks and moves the same everywhere.

## How she moves

Standing about, she isn't playing a clip (`app/renderer/stance.js`). She
stands like a person: mostly still and breathing, now and then moving her
weight onto one leg (hips over that foot, the other knee soft), turning at
the waist when she looks off to the side, and re-placing the free foot,
usually turned out a little. Her arms hang from her shoulders, elbows soft,
palms to her thighs.

What she does in *asterisks* (laughs, claps, waves, shrugs, stretches, blows
a kiss…) is motion capture: Mixamo clips retargeted to her skeleton
(`app/renderer/mocap.js`), blended in from how she's standing and back out.
While she talks her hands move a little. Her face, gaze and head come from
the renderer on top, so she keeps looking at you.

Last of all `app/renderer/collide.js` keeps her elbows, forearms and hands
out of her body. It measures her body from her own mesh when the model
loads, so it fits whatever she's wearing.

The clips live in `app/models/mocap.bin`, built from Mixamo FBX exports in
`app/mocap-src/` by `node app/tools/mocap-build.mjs`. Neither is in git:
Mixamo's terms allow the clips in an app but not sharing the files. Without
the file her actions fall back to the older procedural animations.

There's no bridge on this machine. The app talks to her bridge on lab3, the
same one the iPhone app uses: `http://192.168.1.15:8765` at home,
`https://lab3.tail35b6c6.ts.net` over Tailscale. Same conversation, same memory.

## Voice

- **Mic:** a USB mic, such as the wireless mic's receiver, is used as soon as
  it's plugged in. Unplug it and she goes back to the laptop's own mic. The
  AirPods' mic is never used, because it would drop them to call quality.
- **Her voice:** goes to the AirPods while they're connected over Bluetooth,
  otherwise to the laptop speaker. It switches by itself, mid-sentence too.
  Only her voice moves: the system's default output is left alone.
- **Hands-free** (tray › Listen for "Marina", on by default): she answers
  anything that starts or ends with her name. For a few seconds after she
  answers you can carry on without it. Each phrase goes to her Whisper on lab3
  (`/hear`).
- The mic button records one message. The phone button is a call: everything
  you say goes to her, taking turns.

The tray shows which mic and output she's using. Device names are matched
against the patterns in `~/.config/Marina/config.json` (`audio.input` and
`audio.output`, regular expressions, case-insensitive). If your mic's receiver
has an unusual name, add part of it to `audio.input.prefer`.

## Setup

1. Put the bridge's web token in `~/.config/Marina/bridge.token` (mode 600). It's
   `/etc/appliance/phone.token` on lab3.
2. Install: `sudo apt install ./Marina-*.deb`, or run the AppImage.
3. Tray › Start at login, if you want her there every time.

Shortcuts: Ctrl+Shift+Space talk · Ctrl+Shift+C call · Ctrl+Shift+H show/hide ·
Ctrl+Shift+. stop her.

## Build

The packages contain her model, and the VRoid item licences don't allow
sharing it. Keep `dist/` on your own machines, never in a release or in git.

The AppImage tooling is x86-only, so build on lab2 (or any x64 Linux machine)
with Node 22:

```bash
./build.sh            # copies app/renderer, the model and mocap.bin in, then deb + AppImage
```

To build on lab2 from the Mac without a checkout there, copy this folder over
after running the copy steps from `build.sh`, then run
`npx electron-builder --linux deb AppImage --x64` in it.

Try it on any machine without installing it:
`MARINA_CONFIG_DIR=/tmp/m npx electron .` (with a `bridge.token` in that folder).
