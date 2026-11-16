#!/usr/bin/env python3
"""Add a non-Steam game shortcut to Steam, with a Proton version forced on.

  steam-shortcut.py APPID NAME EXE STARTDIR [COMPAT_TOOL]

Writes userdata/*/config/shortcuts.vdf (binary VDF) and the
CompatToolMapping entry in config/config.vdf. Steam must be closed: it
rewrites both files when it exits. Existing shortcuts are kept; one with the
same appid is replaced.
"""
import glob
import os
import shutil
import struct
import sys

STEAM = os.path.expanduser("~/.local/share/Steam")


# -- binary VDF (shortcuts.vdf) ------------------------------------------------

def read_bvdf(data, i=0):
    out = {}
    while True:
        t = data[i]; i += 1
        if t == 0x08:
            return out, i
        end = data.index(b"\x00", i); key = data[i:end].decode(); i = end + 1
        if t == 0x00:
            out[key], i = read_bvdf(data, i)
        elif t == 0x01:
            end = data.index(b"\x00", i); out[key] = data[i:end].decode(); i = end + 1
        elif t == 0x02:
            out[key] = struct.unpack("<i", data[i:i + 4])[0]; i += 4
        else:
            raise ValueError(f"unknown VDF type {t:#x} at {i}")


def write_bvdf(d):
    b = b""
    for k, v in d.items():
        kb = k.encode() + b"\x00"
        if isinstance(v, dict):
            b += b"\x00" + kb + write_bvdf(v)
        elif isinstance(v, int):
            b += b"\x02" + kb + struct.pack("<i", v)
        else:
            b += b"\x01" + kb + str(v).encode() + b"\x00"
    return b + b"\x08"


def add_shortcut(appid, name, exe, startdir):
    signed = appid - (1 << 32) if appid >= 1 << 31 else appid
    for cfg in glob.glob(f"{STEAM}/userdata/*/config"):
        path = os.path.join(cfg, "shortcuts.vdf")
        root = {"shortcuts": {}}
        if os.path.exists(path):
            shutil.copy(path, path + ".bak")
            data = open(path, "rb").read()
            root, _ = read_bvdf(data[1:], len("shortcuts") + 1) if data[:1] == b"\x00" else (root, 0)
            root = {"shortcuts": root}
        items = [v for v in root["shortcuts"].values() if v.get("appid") != signed]
        items.append({
            "appid": signed, "AppName": name, "Exe": f'"{exe}"', "StartDir": f'"{startdir}"',
            "icon": "", "ShortcutPath": "", "LaunchOptions": "", "IsHidden": 0,
            "AllowDesktopConfig": 1, "AllowOverlay": 1, "OpenVR": 0, "Devkit": 0,
            "DevkitGameID": "", "DevkitOverrideAppID": 0, "LastPlayTime": 0,
            "FlatpakAppID": "", "tags": {},
        })
        root["shortcuts"] = {str(i): v for i, v in enumerate(items)}
        open(path, "wb").write(write_bvdf(root))
        print("shortcut written:", path)


# -- text VDF (config.vdf) ----------------------------------------------------

def force_compat(appid, tool):
    path = f"{STEAM}/config/config.vdf"
    shutil.copy(path, path + ".bak")
    lines = open(path).read().split("\n")
    entry = [f'\t\t\t\t\t"{appid}"', "\t\t\t\t\t{", f'\t\t\t\t\t\t"name"\t\t"{tool}"',
             '\t\t\t\t\t\t"config"\t\t""', '\t\t\t\t\t\t"priority"\t\t"250"', "\t\t\t\t\t}"]
    for i, l in enumerate(lines):
        if l == '\t\t\t\t"CompatToolMapping"':
            # drop an existing entry for this appid, then add ours after the brace
            j = i + 2
            while lines[j] != "\t\t\t\t}":
                if lines[j] == f'\t\t\t\t\t"{appid}"':
                    del lines[j:j + 6]
                    continue
                j += 1
            lines[i + 2:i + 2] = entry
            break
    else:
        steam = lines.index('\t\t\t"Steam"')
        lines[steam + 2:steam + 2] = ['\t\t\t\t"CompatToolMapping"', "\t\t\t\t{", *entry, "\t\t\t\t}"]
    open(path, "w").write("\n".join(lines))
    print(f"compat tool {tool} forced for {appid}")


def main():
    appid, name, exe, startdir = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    tool = sys.argv[5] if len(sys.argv) > 5 else "proton_experimental"
    add_shortcut(appid, name, exe, startdir)
    force_compat(appid, tool)


if __name__ == "__main__":
    main()
