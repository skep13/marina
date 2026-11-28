"""Which model answers a Narwhal message: the abliterated security model or
KAT-Coder. Decided per message from what it says, with no model call, so
routing itself costs nothing.

Every switch between the two is a cold model load on lab3 (tens of seconds,
and RAM is tight there), so a session stays on the model it last used unless
the new message clearly belongs to the other side. Security wins a close
call: KAT-Coder may refuse exploit work, the security model won't.
"""

import re

from process import config as cfg

SECURITY, CODE, CLAUDE = "security", "code", "claude"
ROUTES = (SECURITY, CODE)        # what Auto chooses between
# Claude Code on lab3 is picked by hand only (it costs subscription usage).
PICKABLE = ROUTES + (CLAUDE,)

# (pattern, weight). Patterns are matched case-insensitively on word bounds.
_SECURITY = [
    (r"cve-\d{4}-\d+", 4), (r"exploit\w*", 3), (r"payloads?", 2), (r"shellcode", 4),
    (r"priv(ilege)?[ -]?esc\w*", 4), (r"pentest\w*|penetration test\w*", 4),
    (r"red[ -]team\w*", 3), (r"blue[ -]team\w*", 2), (r"ctf", 3), (r"nmap", 4),
    (r"metasploit|msfvenom|msfconsole", 4), (r"burp( suite)?", 3), (r"sqlmap", 4),
    (r"hashcat|john the ripper", 4), (r"mimikatz|bloodhound|impacket|kerberoast\w*", 4),
    (r"sql injection|sqli|xss|csrf|ssrf|xxe|rce|lfi|rfi|idor", 3),
    (r"reverse shell|bind shell|web ?shell", 4), (r"c2|command and control", 3),
    (r"malware|ransomware|rootkit|keylogger|trojan|botnet", 3),
    (r"phishing|social engineering", 3), (r"vulnerabilit\w+|vuln\w*", 2),
    (r"attack surface|recon(naissance)?|enumerat\w+", 2), (r"osint", 3),
    (r"brute[ -]?forc\w+|password crack\w*|crack(ing)? (the )?hash\w*", 3),
    (r"buffer overflow|rop chain|heap spray|use[ -]after[ -]free", 4),
    (r"fuzz\w*", 2), (r"wireshark|tcpdump|pcap", 2), (r"firewall|ids|ips|siem|edr|av evasion", 2),
    (r"bypass\w*", 1), (r"hack\w*", 2), (r"decrypt\w*|encrypt\w*", 1), (r"forensic\w*", 2),
    (r"threat model\w*|threat hunt\w*", 2), (r"nessus|openvas|nikto|gobuster|ffuf|dirb", 4),
    (r"hardening|harden\w*", 2), (r"jwt|oauth|kerberos|ntlm|ldap", 1),
    (r"port scan\w*|open ports?|scan(ning)? (the |my )?(network|host|subnet)", 3),
    (r"security|cyber\w*|infosec", 2), (r"wifi crack\w*|aircrack\w*|deauth\w*", 4),
]

_CODE = [
    (r"```", 3), (r"traceback \(most recent call last\)", 4), (r"stack ?trace", 3),
    (r"refactor\w*", 3), (r"unit tests?|pytest|jest|test suite", 3), (r"debug\w*", 2),
    (r"compile\w*|compiler|linker|build (error|fails?|failed)", 3), (r"syntax error|type ?error", 3),
    (r"function|method|class|variable|struct|enum|interface", 1), (r"regex|regular expression", 2),
    (r"python|javascript|typescript|rust|golang|swift|kotlin|java|c\+\+|c#|ruby|php|bash script", 2),
    (r"react|svelte|vue|django|flask|fastapi|node(\.js)?|express|swiftui|tokio|serde", 2),
    (r"api|endpoint|json|yaml|sql query|database schema|migration", 1),
    (r"git (rebase|merge|commit|diff|push|pull)|merge conflict|pull request", 2),
    (r"implement\w*|write (a |me a |the )?(function|script|program|class|module|cli)", 3),
    (r"code review|review (this|my) code|code", 2), (r"algorithm|big[- ]o|complexity", 2),
    (r"npm|pip|cargo|gradle|xcode|cmake|makefile|dockerfile", 2),
    (r"lint\w*|formatter|type hints?|generics?", 2), (r"bug|segfault|null pointer|panic(ked)?", 2),
]

_FILE_EXT = re.compile(r"\b[\w/.-]+\.(py|js|ts|tsx|jsx|rs|go|swift|kt|java|cpp|cc|c|h|rb|php|cs|sh|"
                       r"toml|yaml|yml|json|sql|html|css|vue|svelte)\b", re.I)
_CODE_LINE = re.compile(r"^\s*(def |class |fn |func |import |from \S+ import |#include|let |const |"
                        r"var |pub |impl |public |private |return |if .+:|for .+:|\}|\{)", re.M)


def _compile(table):
    return [(re.compile(rf"(?<![\w-])(?:{p})(?![\w])", re.I), w) for p, w in table]


_SEC_RX, _CODE_RX = _compile(_SECURITY), _compile(_CODE)

# The other side has to beat the session's current model by this much
# before a switch (and its load time) is worth it.
STICKY_MARGIN = 3
# A first message has to show at least this much to leave the default.
MIN_SIGNAL = 2


def scores(text):
    text = text or ""
    sec = sum(w for rx, w in _SEC_RX if rx.search(text))
    code = sum(w for rx, w in _CODE_RX if rx.search(text))
    if _FILE_EXT.search(text):
        code += 2
    if len(_CODE_LINE.findall(text)) >= 2:
        code += 3
    return sec, code


def default_route():
    r = str(cfg.setting("narwhal", "default_route", SECURITY) or SECURITY)
    return r if r in ROUTES else SECURITY


def choose(text, last=None):
    """(route, reason) for one message. `last` is the route the session used
    for its previous answer, if any."""
    sec, code = scores(text)
    if last in ROUTES:
        mine, other = (sec, code) if last == SECURITY else (code, sec)
        if other - mine >= STICKY_MARGIN:
            new = CODE if last == SECURITY else SECURITY
            return new, f"looks like {_name(new)} work (score {other} vs {mine})"
        return last, "same model as the last answer" if max(sec, code) < MIN_SIGNAL else \
            f"stays on {_name(last)} (score {mine} vs {other})"
    if max(sec, code) < MIN_SIGNAL:
        return default_route(), "no clear signal, default model"
    if sec >= code:
        return SECURITY, f"looks like security work (score {sec} vs {code})"
    return CODE, f"looks like coding work (score {code} vs {sec})"


def _name(route):
    return "security" if route == SECURITY else "coding"


def model_for(route):
    if route == CLAUDE:
        return "claude"
    if route == CODE:
        return str(cfg.setting("narwhal", "code_model", "forge") or "forge")
    return str(cfg.setting("narwhal", "model", "narwhal") or "narwhal")


def label_for(route):
    """What the apps show under an answer."""
    if route == CLAUDE:
        return "Claude"
    if route == CODE:
        return str(cfg.setting("narwhal", "code_label", "KAT-Coder") or "KAT-Coder")
    return str(cfg.setting("narwhal", "label", "Narwhal · abliterated") or "Narwhal · abliterated")


def system_for(route):
    key = {CODE: "code_system", CLAUDE: "claude_system"}.get(route, "system")
    return str(cfg.setting("narwhal", key, "") or "").strip()


def context_for(route):
    """The model's context window in tokens, for the meter. Set to match
    llama-swap's -c for each model."""
    key = {CODE: "code_context", CLAUDE: "claude_context"}.get(route, "context")
    default = 200000 if route == CLAUDE else 131072
    try:
        return int(cfg.setting("narwhal", key, default) or default)
    except (TypeError, ValueError):
        return 131072
