#!/usr/bin/env python3
"""Documentation check: relative links, heading anchors, backticked repo paths and privacy patterns.

Usage: python scripts/check_docs.py [repo_root] [--mermaid] [files...]
Exit status 1 if any issue is found. --mermaid also renders every mermaid block
(needs `mmdc` from @mermaid-js/mermaid-cli on PATH or in $MMDC).
"""
import os, re, sys, subprocess, tempfile, unicodedata

args = [a for a in sys.argv[1:] if not a.startswith("--")]
root = os.path.abspath(args[0] if args else ".")
do_mermaid = "--mermaid" in sys.argv
explicit = args[1:]
MMDC = os.environ.get("MMDC", "mmdc")

def md_files():
    if explicit:
        return [os.path.abspath(f) for f in explicit]
    out = subprocess.run(["git", "-C", root, "ls-files", "-co", "--exclude-standard", "*.md"],
                         capture_output=True, text=True).stdout.split()
    return [os.path.join(root, f) for f in out]

def slug(h):
    h = h.strip().lower()
    h = re.sub(r"`", "", h)
    h = re.sub(r"[^\w\- ]", "", h, flags=re.UNICODE)
    return h.replace(" ", "-")

anchor_cache = {}
def anchors(path):
    if path in anchor_cache: return anchor_cache[path]
    seen, res = {}, set()
    infence = False
    for line in open(path, encoding="utf-8", errors="ignore"):
        if line.lstrip().startswith("```"): infence = not infence; continue
        if infence: continue
        m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            s = slug(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1)))
            n = seen.get(s, 0); seen[s] = n + 1
            res.add(s if n == 0 else f"{s}-{n}")
        for a in re.findall(r'<a (?:name|id)="([^"]+)"', line): res.add(a)
    anchor_cache[path] = res
    return res

PRIV = [
    (r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b", "tailscale-ip"),
    (r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "private-ip-10"),
    (r"\b192\.168\.\d{1,3}\.\d{1,3}\b", "private-ip-192"),
    (r"\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b", "private-ip-172"),
    (r"/Users/[A-Za-z]", "abs-user-path"),
    (r"/home/[a-z]", "abs-home-path"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.(com|edu|org|net|local)\b", "email"),
    (r"(ghp_|github_pat_|hf_[A-Za-z0-9]{20}|sk-[A-Za-z0-9]{20})", "token"),
    (r"BEGIN [A-Z ]*PRIVATE KEY", "private-key"),
    (r"team15_pi_ed25519|id_ed25519|id_rsa", "ssh-key-name"),
    (r"Team15-Rescue|BASE-X", "ssid"),
    (r"team15@", "user@host"),
    (r"EatnHamSandwich", "handle-from-log"),
    (r"\.claude/projects|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl", "transcript-path"),
]
ALLOW_EMAIL = {"noreply@anthropic.com", "noreply@github.com", "git@github.com"}
# Exact strings that match a pattern but are public, documented values.
ALLOW = {("TEAM15_DRONE_SEARCH_BUILD.md", "id_ed25519"),   # generic ssh-keygen example
         ("TEAM15_DRONE_SEARCH_BUILD.md", "192.168.10.1")}  # Tello vendor default address

errs = []
files = md_files()
mermaid_blocks = []
for f in files:
    rel = os.path.relpath(f, root)
    text = open(f, encoding="utf-8", errors="ignore").read()
    # privacy
    for pat, name in PRIV:
        for m in re.finditer(pat, text):
            if (rel, m.group(0)) in ALLOW: continue
            if name == "email" and (m.group(0) in ALLOW_EMAIL or m.group(0).endswith("users.noreply.github.com")): continue
            ln = text[:m.start()].count("\n") + 1
            errs.append(f"PRIVACY[{name}] {rel}:{ln}: {m.group(0)}")
    # links (skip code fences)
    stripped = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    stripped_inline = re.sub(r"`[^`\n]*`", "``", stripped)
    for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", stripped_inline):
        target = m.group(1)
        ln = stripped_inline[:m.start()].count("\n") + 1
        if re.match(r"^(https?:|mailto:)", target): continue
        path, _, frag = target.partition("#")
        tpath = f if path == "" else os.path.normpath(os.path.join(os.path.dirname(f), path))
        if not os.path.exists(tpath):
            errs.append(f"LINK {rel}:{ln}: missing target {target}"); continue
        if frag and tpath.endswith(".md") and frag not in anchors(tpath):
            errs.append(f"ANCHOR {rel}:{ln}: #{frag} not in {os.path.relpath(tpath, root)}")
    # backticked repo paths
    if rel.startswith("docs/") or rel == "README.md":
        for m in re.finditer(r"`((?:[A-Za-z0-9_.\-]+/)+[A-Za-z0-9_.\-]+\.(?:py|md|json|yml|yaml|ino|sh|html|h|csv|txt|ini))`", stripped):
            p = m.group(1)
            if p.startswith(("$", "~", "/")) or "<" in p or "*" in p: continue
            cand = [os.path.join(root, p), os.path.normpath(os.path.join(os.path.dirname(f), p))]
            if not any(os.path.exists(c) for c in cand):
                ln = stripped[:m.start()].count("\n") + 1
                errs.append(f"PATH {rel}:{ln}: `{p}` not found in repo")
    for m in re.finditer(r"```mermaid\n(.*?)```", text, flags=re.S):
        mermaid_blocks.append((rel, text[:m.start()].count("\n") + 1, m.group(1)))

if do_mermaid:
    tmp = tempfile.mkdtemp()
    for i, (rel, ln, body) in enumerate(mermaid_blocks):
        src = os.path.join(tmp, f"m{i}.mmd"); open(src, "w").write(body)
        r = subprocess.run([MMDC, "-q", "-i", src, "-o", os.path.join(tmp, f"m{i}.svg")], capture_output=True, text=True)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip().splitlines()
            msg = next((l for l in msg if "Error" in l or "error" in l), msg[0] if msg else "?")
            errs.append(f"MERMAID {rel}:{ln}: {msg[:200]}")

for e in errs: print(e)
print(f"\n{len(files)} md files, {len(mermaid_blocks)} mermaid blocks, {len(errs)} issues")
sys.exit(1 if errs else 0)
