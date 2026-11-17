# ====================================================================
#  Songbird display - device firmware (MicroPython, ESP32-S3)
#
#  Subscribes to the broker and shows whatever Songbird publishes to
#  TOPIC on the OLED: a title in the yellow strip, the body (scrolling
#  if long) in the blue area. Output only - it runs nothing.
#
#  Payload may be JSON {"title": "...", "text": "..."} or plain text.
#  An empty text (or "clear") returns to the logo.
# ====================================================================
import time
import json
import framebuf
import network
from machine import Pin, I2C

import ssl
import ssd1306
import logo as logomod
import config as C
import dns
from umqtt.simple import MQTTClient

i2c = I2C(0, scl=Pin(9), sda=Pin(8), freq=400000)
oled = ssd1306.SSD1306_I2C(128, 64, i2c)

_new = None          # latest incoming (title, text)


def status(*lines):
    oled.fill(0)
    y = 2
    for ln in lines:
        oled.text(str(ln)[:16], 2, y, 1)
        y += 12
    oled.show()


def wrap(s, width=16):              # 8px font -> 16 chars fit across 128px
    out, line = [], ""
    for word in str(s).split():
        while len(word) > width:
            if line:
                out.append(line); line = ""
            out.append(word[:width]); word = word[width:]
        if len(line) + len(word) + (1 if line else 0) <= width:
            line = (line + " " + word) if line else word
        else:
            if line:
                out.append(line)
            line = word
    if line:
        out.append(line)
    return out


def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        wlan.config(hostname=C.MDNS_NAME)
    except Exception:
        pass
    if not wlan.isconnected():
        status("Wi-Fi...", C.WIFI_SSID)
        wlan.connect(C.WIFI_SSID, C.WIFI_PASS)
        t0 = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > 20000:
                raise OSError("wifi timeout")
            time.sleep_ms(250)
    return wlan.ifconfig()[0]


def _tls():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        with open(C.BROKER_CERT) as f:
            ctx.load_verify_locations(cadata=f.read())
        ctx.verify_mode = ssl.CERT_REQUIRED
    except Exception:
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def mqtt_connect():
    ctx = _tls() if C.MQTT_TLS else None
    host = C.MQTT_BROKER
    server = host
    pub = getattr(C, "PUBLIC_DNS", None)
    if pub:                                        # hotspot DNS lies; resolve ourselves
        try:
            server = dns.resolve(host, pub) or host
        except Exception:
            server = host
    c = MQTTClient(C.DEVICE_ID, server, port=C.MQTT_PORT,
                   user=C.MQTT_USER, password=C.MQTT_PASS, keepalive=30, ssl=ctx)
    c.sni = host                                   # TLS SNI + cert name stay the hostname
    c.set_callback(on_message)
    c.connect()
    c.subscribe(C.TOPIC)
    return c


def on_message(topic, payload):
    global _new
    title, text = "SONGBIRD", ""
    try:
        d = json.loads(payload)
        text = d.get("text", "")
        title = d.get("title", "SONGBIRD")
    except Exception:
        text = payload.decode() if isinstance(payload, bytes) else str(payload)
    _new = (title, text)


# --- scaled text: short messages render big, long ones shrink to 8px ---
_cfb = framebuf.FrameBuffer(bytearray(8), 8, 8, framebuf.MONO_HLSB)


def _char(x, y, ch, s):
    if s == 1:
        oled.text(ch, x, y, 1)
        return
    _cfb.fill(0)
    _cfb.text(ch, 0, 0, 1)
    for yy in range(8):
        for xx in range(8):
            if _cfb.pixel(xx, yy):
                oled.fill_rect(x + xx * s, y + yy * s, s, s, 1)


def fit_scale(text, w, h, maxs=4):
    # largest integer scale whose wrapped text fits w x h
    for s in range(maxs, 0, -1):
        cpl = max(1, w // (8 * s))
        lines = wrap(text, cpl)
        maxl = max(1, h // (8 * s))
        if len(lines) <= maxl:
            return s, lines, maxl
    cpl = max(1, w // 8)
    return 1, wrap(text, cpl), max(1, h // 8)


def show_message(title, text):
    BX, BY, BW, BH = 2, 16, 124, 46                 # blue area
    s, lines, maxl = fit_scale(text, BW, BH)
    off = 0
    last = time.ticks_ms()
    hold_until = time.ticks_add(time.ticks_ms(), C.HOLD_S * 1000) if C.HOLD_S else None
    while True:
        if _new is not None or (hold_until and time.ticks_diff(hold_until, time.ticks_ms()) <= 0):
            return
        if len(lines) > maxl and time.ticks_diff(time.ticks_ms(), last) > 1400:
            off = (off + 1) % (len(lines) - maxl + 1)
            last = time.ticks_ms()
        oled.fill(0)
        oled.text(title[:16], 2, 3, 1)              # yellow strip
        oled.line(0, 13, 128, 13, 1)
        shown = lines[off:off + maxl]
        lh = 8 * s
        y = BY + max(0, (BH - len(shown) * lh) // 2)
        for ln in shown:
            lw = len(ln) * 8 * s
            x = BX + max(0, (BW - lw) // 2)
            cx = x
            for ch in ln:
                _char(cx, y, ch, s)
                cx += 8 * s
            y += lh
        oled.show()
        _sleep_check(0.08)


def _sleep_check(sec):
    # sleep while still servicing MQTT so new messages are caught promptly
    end = time.ticks_add(time.ticks_ms(), int(sec * 1000))
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        try:
            _client.check_msg()
        except Exception:
            pass
        time.sleep_ms(20)


_client = None


def run():
    global _new, _client
    ip = wifi_connect()
    logomod.draw_logo(oled, "connecting...")
    _client = mqtt_connect()
    logomod.draw_logo(oled, ip)
    last_ping = time.ticks_ms()
    while True:
        try:
            _client.check_msg()
            if _new is not None:
                title, text = _new
                _new = None
                if not text or text.strip().lower() == "clear":
                    logomod.draw_logo(oled, ip)
                else:
                    show_message(title, text)
                    if _new is None:
                        logomod.draw_logo(oled, ip)
            if time.ticks_diff(time.ticks_ms(), last_ping) > 15000:
                _client.ping()
                last_ping = time.ticks_ms()
            time.sleep_ms(50)
        except OSError:
            status("reconnecting...")
            time.sleep(2)
            try:
                _client = mqtt_connect()
                logomod.draw_logo(oled, ip)
            except Exception:
                time.sleep(3)


run()
