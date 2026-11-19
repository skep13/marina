# Marina for iPhone

A native iPhone app for talking to Marina away from the Mac, without
Telegram or a browser. It's SwiftUI, with her avatar drawn by the same renderer
(`app/renderer`) and the same VRM (`app/models/model.vrm`) as the Mac app, so she
looks and moves the same. Both are copied into the app when it's built, so it
never downloads them.

- Type to her, or hold the mic for a voice note (slide away to cancel).
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

## What it can't do

- No push notifications. Apple only gives those to paid developer accounts,
  so her unprompted messages reach you while the app is open or just closed.
- No calls yet; voice notes cover talking to her.
