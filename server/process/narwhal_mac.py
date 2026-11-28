"""Tools that let Narwhal's lab3 models work on the owner's Mac.

The model runs on lab3, but the files are on the Mac, so the bridge doesn't
run these itself: it hands each call to the Narwhal Mac app (as a
"mac_tool" event on the watch stream), the app runs it on the Mac (asking
the owner first for anything that changes something), and posts the result
back. Only messages sent from the Mac app get these tools: the phone has no
way to reach the Mac's files.
"""

import json

TOOLS = [
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List a folder on the user's Mac (names, sizes, and which are folders).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Folder path on the Mac, e.g. ~/narwhal/app"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file on the user's Mac. Long files come back in parts: pass "
                       "start_line to read further.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "description": "First line to read (1-based). Default 1."}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "search_files",
        "description": "Search the text of files under a folder on the user's Mac (like grep -rn).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Folder to search in."},
            "pattern": {"type": "string", "description": "Text or regular expression to find."}},
            "required": ["path", "pattern"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a text file on the user's Mac with the full new content. "
                       "The user approves it first.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string", "description": "The whole file as it should be."}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a shell command on the user's Mac (zsh) and get its output. The user "
                       "approves it first. Avoid commands that run forever.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
            "cwd": {"type": "string", "description": "Folder to run it in. Default ~."}},
            "required": ["command"]}}},
]

NAMES = {t["function"]["name"] for t in TOOLS}

NOTE = ("You can work on the user's Mac with list_dir, read_file, search_files, write_file and "
        "run_command. They run on the Mac, not on lab3, so use Mac paths (~ is the user's home). "
        "Look before you change anything. write_file and run_command ask the user first; if they "
        "say no, accept it and carry on without.")


def parse(args):
    if isinstance(args, dict):
        return args
    try:
        v = json.loads(args or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def step(name, args):
    """The line the apps show for a call, like Claude Code's steps."""
    a = parse(args)
    label = {"list_dir": "List", "read_file": "Read", "search_files": "Search files",
             "write_file": "Write", "run_command": "Run"}.get(name, name)
    what = a.get("command") or a.get("path") or ""
    if name == "search_files":
        what = f"{a.get('pattern', '')}  in {a.get('path', '')}"
    return f"▸ {label}  {str(what).splitlines()[0][:160] if what else ''}".rstrip()
