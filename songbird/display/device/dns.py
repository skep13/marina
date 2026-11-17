# Minimal A-record resolver querying a chosen public DNS directly.
# Needed because some hotspots hand out a private/wrong answer for the
# broker's Funnel hostname; we ask 8.8.8.8 ourselves and connect by IP
# (with the hostname kept as the TLS SNI).
import socket
import struct
import random


def resolve(host, server="8.8.8.8", timeout=5):
    hdr = struct.pack(">HHHHHH", random.getrandbits(16), 0x0100, 1, 0, 0, 0)
    q = b""
    for p in host.split("."):
        q += bytes([len(p)]) + p.encode()
    q += b"\x00" + struct.pack(">HH", 1, 1)      # type A, class IN
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(hdr + q, (server, 53))
        data, _ = s.recvfrom(512)
    finally:
        s.close()
    an = struct.unpack(">H", data[6:8])[0]
    i = 12
    while data[i] != 0:
        i += 1 + data[i]
    i += 5                                        # null + qtype + qclass
    for _ in range(an):
        if data[i] & 0xC0 == 0xC0:
            i += 2
        else:
            while data[i] != 0:
                i += 1 + data[i]
            i += 1
        rtype, _c, _ttl, rdlen = struct.unpack(">HHIH", data[i:i + 10])
        i += 10
        if rtype == 1 and rdlen == 4:
            return "%d.%d.%d.%d" % tuple(data[i:i + 4])
        i += rdlen
    return None
