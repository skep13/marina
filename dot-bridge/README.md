# dot-bridge

Lets Marina use the stock Echo Dot in the bedroom as her microphone and
speaker, with nothing opened, flashed or bought, by holding an Alexa Drop In
call open to it from an Android emulator on the home lab.

Runs in container 114 (`dot-bridge`) on lab2.

- `dot-display`: a virtual 720x1280 screen, viewable in a browser at
  `http://192.168.1.248:6080/vnc.html`. The VNC password is in
  `/root/vnc-password` in the container.
- `dot-audio`: PulseAudio with two virtual devices. `dot_ear` is what the
  emulator plays (the Dot's microphone during a Drop In); `dot_mouth` is
  what Marina says, fed to the emulator as its microphone.
- `dot-emulator`: Android 14 with the Play Store, AVD `dot`.
- `dot-ear` (`dot_ear.py`): listens to `dot_ear` for her name, asks the
  bridge (`marina-voice` on `/v1/`) and plays her answer into `dot_mouth`.
  Set `MARINA_BRIDGE`, `MARINA_SPEECH` and `MARINA_KEY` in
  `/etc/dot-bridge.env`. The bridge needs `satellite.enabled` and `api.key`.
  It points at the always-on bridge on lab3 (ct110, 192.168.1.15).
- `dot-call` (`dot_call.py`): keeps the Drop In open, redialling when it
  drops. Set `DOT_NAME` in `/etc/dot-bridge.env` to the Dot's name as the Alexa app shows it.

The Alexa app only allows Drop In once the profile has a verified mobile
number (Alexa app, More, Settings, Your Profile, Set Mobile Number).

Install or update from the Mac:

    ./install.sh
