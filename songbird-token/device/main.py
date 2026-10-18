# ====================================================================
#  Songbird approval token - device firmware (MicroPython, ESP32-S3)
#
#  Idle: shows the logo. On an MQTT request it shows the EXACT command and
#  waits for the onboard BOOT button (GPIO0). The button is ignored for the
#  first MIN_VIEW_MS so you can't blind-approve; long commands scroll so you
#  can read all of it. A press signs HMAC(secret, id|nonce|command) - the
#  signature commits to the exact command shown, so the model cannot display
#  one thing and run another. No press within the timeout = DENY.
# ====================================================================
import time
import json
import binascii
import network
import machine
from machine import Pin, I2C

import ssl
import ssd1306
import logo as logomod
import config as C
from hmac256 import hexdigest
from umqtt.simple import MQTTClient

i2c = I2C(0, scl=Pin(9), sda=Pin(8), freq=400000)
oled = ssd1306.SSD1306_I2C(128, 64, i2c)
button = Pin(0, Pin.IN, Pin.PULL_UP)        # BOOT button: pressed == 0

SECRET = binascii.unhexlify(C.SECRET_HEX)
_pending = None


def msg(*lines):
    oled.fill(0)
    y = 2
    for ln in lines:
        oled.text(str(ln)[:21], 2, y, 1)
        y += 12
    oled.show()


def wrap(s, width=21):
    out, line = [], ""
    for word in str(s).split():
        while len(word) > width:                 # hard-break very long tokens
            if line:
                out.append(line)
                line = ""
            out.append(word[:width])
            word = word[width:]
        if len(line) + len(word) + (1 if line else 0) <= width:
            line = (line + " " + word) if line else word
        else:
            if line:
                out.append(line)
            line = word
    if line:
        out.append(line)
    return out


def pressed():
    if button.value() == 0:
        time.sleep_ms(25)
        return button.value() == 0
    return False


def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        wlan.config(hostname=C.MDNS_NAME)
    except Exception:
        pass
    if not wlan.isconnected():
        msg("Wi-Fi...", C.WIFI_SSID)
        wlan.connect(C.WIFI_SSID, C.WIFI_PASS)
        t0 = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), t0) > 20000:
                raise OSError("wifi timeout")
            time.sleep_ms(250)
    return wlan.ifconfig()[0]


def _tls_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        with open(C.BROKER_CERT) as f:
            ctx.load_verify_locations(cadata=f.read())
        ctx.verify_mode = ssl.CERT_REQUIRED      # verify the broker's cert chain
    except Exception:
        ctx.verify_mode = ssl.CERT_NONE          # fallback if cert missing
    return ctx


def mqtt_connect():
    ctx = _tls_context() if C.MQTT_TLS else None
    c = MQTTClient(
        C.DEVICE_ID, C.MQTT_BROKER, port=C.MQTT_PORT,
        user=C.MQTT_USER, password=C.MQTT_PASS,
        keepalive=30, ssl=ctx,
    )
    c.set_callback(on_message)
    c.connect()
    c.subscribe(C.REQ_TOPIC)
    return c


def on_message(topic, payload):
    global _pending
    try:
        req = json.loads(payload)
        if "id" in req and "nonce" in req and "cmd" in req:
            _pending = req
    except Exception:
        pass


def ask(client, req):
    """Show the exact command, enforce min-view, scroll, wait for press/timeout."""
    rid = req.get("id", "")
    nonce = req.get("nonce", "")
    cmd = req.get("cmd", "")

    lines = wrap(cmd)
    visible = 3                                  # body rows between header/footer
    offset = 0
    last_scroll = time.ticks_ms()

    start = time.ticks_ms()
    deadline = time.ticks_add(start, C.APPROVE_TIMEOUT_MS)
    approved = False
    while button.value() == 0:                   # ignore a stale held press
        time.sleep_ms(10)

    while True:
        now = time.ticks_ms()
        remain = time.ticks_diff(deadline, now)
        if remain <= 0:
            break
        locked = time.ticks_diff(now, start) < C.MIN_VIEW_MS

        if len(lines) > visible and time.ticks_diff(now, last_scroll) > 1400:
            offset = (offset + 1) % (len(lines) - visible + 1)
            last_scroll = now

        oled.fill(0)
        oled.rect(0, 0, 128, 64, 1)
        oled.text("APPROVE?", 2, 3, 1)
        oled.text("{:>2}s".format(remain // 1000), 104, 3, 1)
        y = 16
        for ln in lines[offset:offset + visible]:
            oled.text(ln, 4, y, 1)
            y += 10
        oled.text("reading..." if locked else "BOOT=run  wait=no", 2, 52, 1)
        oled.show()

        if not locked and pressed():
            approved = True
            break
        time.sleep_ms(50)

    token = hexdigest(SECRET, "{}|{}|{}".format(rid, nonce, cmd)) if approved else ""
    resp = {"id": rid, "nonce": nonce, "approved": approved, "token": token}
    client.publish(C.RESP_TOPIC, json.dumps(resp))

    msg("APPROVED" if approved else "DENIED", cmd[:21])
    time.sleep(1)


def run():
    global _pending
    ip = wifi_connect()
    logomod.draw_logo(oled, "connecting...")
    client = mqtt_connect()
    logomod.draw_logo(oled, ip)
    last_ping = time.ticks_ms()

    while True:
        try:
            client.check_msg()
            if _pending is not None:
                req, _pending = _pending, None
                ask(client, req)
                logomod.draw_logo(oled, ip)
            if time.ticks_diff(time.ticks_ms(), last_ping) > 15000:
                client.ping()
                last_ping = time.ticks_ms()
            time.sleep_ms(50)
        except OSError:
            msg("reconnecting...")
            time.sleep(2)
            try:
                client = mqtt_connect()
                logomod.draw_logo(oled, ip)
            except Exception:
                time.sleep(3)


run()
