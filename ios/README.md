# Marina for iPhone

A native iPhone app for talking to Marina away from the Mac, without
Telegram or a browser. It's SwiftUI, with her avatar drawn by the same renderer
(`app/renderer`) and the same VRM (`app/models/model.vrm`) as the Mac app, so she
looks and moves the same. Both are copied into the app when it's built, so it
never downloads them.

- Type to her, or hold the mic for a voice note (slide away to cancel).
- **Hands-free** (the ear button): the mic stays open, with the screen locked
  too, and she answers anything that starts or ends with her name ("Marina,
  …", "…, Marina?"). For a few seconds after she answers you can carry on
  without her name. A wireless mic's USB-C receiver is used automatically
  when it's plugged in. Each phrase goes to her Whisper on lab3 (`/hear`);
  anything not said to her is dropped there. iOS shows the orange mic dot
  while it's on, and it costs battery.
- **While she works** on lab2 (or your Mac) a panel shows each step, a live
  view of lab2's screens (tap it for full size), and **Stop**, which also
  kills the command she's running there.
- She answers sentence by sentence in her own voice, with lip sync. The
  speaker button turns her voice off and keeps the text.
- It's the same conversation and memory as everywhere else: it talks to her
  bridge on lab3 (ct110, `http://192.168.1.15:8765`).
- While the app is open she can start talking herself (timers, follow-ups,
  checking in). If you've just left the app, that arrives as a notification.
- Anything she wants to do on a computer that needs your OK shows Allow / Deny.

## Build

Needs Xcode (from the App Store, with the iOS platform) and XcodeGen
(`brew install xcodegen`). The renderer's `vendor/vrm-bundle.js` must exist;
`./setup-mac.sh` builds it.

```bash
ios/build-ipa.sh          # → ios/dist/Marina.ipa, unsigned
ios/build-ipa.sh --sim    # build and run it in the iPhone simulator
```

`Marina.xcodeproj` is generated from `project.yml` (`cd ios && xcodegen`), so
edit `project.yml`, not the project.

## Install with Sideloadly

1. Plug the iPhone in, open Sideloadly, drag in `ios/dist/Marina.ipa`, and
   sign in with your Apple ID.
2. On the phone: Settings › General › VPN & Device Management › trust your
   Apple ID. Developer Mode must be on (Settings › Privacy & Security).
3. With a free Apple ID the app stops opening after 7 days. Turn on
   Sideloadly's automatic refresh, or plug in and reinstall. Nothing is lost:
   her memory and the conversation live on lab3.

## Connect

1. Install **Tailscale** from the App Store and sign in with the same account
   as the Mac. lab3 routes `192.168.1.15`, so the same address works at home
   and away.
2. In the app: ⋯ › Settings. The address is `http://192.168.1.15:8765`. The
   token is the bridge's web token, in `/etc/appliance/phone.token` on lab3.
   It's kept in the phone's Keychain. **Test connection**, then **Done**.

## Notifications with the app closed (ntfy)

A free Apple ID gets no push of its own, so her reminders, timers and
messages come through **ntfy**, self-hosted on lab3 (ct110, `ntfy.service`,
published on the tailnet by `tailscale serve --https=10000`). Message text
stays on lab3; ntfy.sh only relays a wake-up to Apple.

1. Install **ntfy** from the App Store.
2. In it: **+** › *Use another server* › `https://lab3.tail35b6c6.ts.net:10000`,
   topic: the `topic=` line of `/var/lib/marina/ntfy.secret` in ct110.
3. Tapping one of her notifications opens this app (`marinaapp://open`).

The app tells the bridge when it's on screen (`/presence`). While it is, she
just talks here; in the background she pushes instead. With hands-free on
she stays able to talk in the background, so she speaks reminders out loud.

## What it can't do

- No calls; hands-free and voice notes cover talking to her.
