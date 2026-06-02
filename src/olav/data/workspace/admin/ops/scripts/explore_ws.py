#!/usr/bin/env python3
"""Explore workspace: list files, grep content."""
import os, glob, json, sys

WS = "/home/yhvh/Olav/.olav/workspace"

def op1():
    files = sorted(glob.glob(os.path.join(WS, "**/*.md"), recursive=True))
    total = len(files)
    limited = files[:80]
    return {"op": 1, "desc": "All .md files (max 80)", "total": total, "list": limited}

def op2():
    all_cfg = []
    for ext in ["yaml", "yml", "json", "toml"]:
        all_cfg.extend(glob.glob(os.path.join(WS, f"**/*.{ext}"), recursive=True))
    all_cfg.sort()
    total = len(all_cfg)
    limited = all_cfg[:40]
    return {"op": 2, "desc": "Config files .yaml/.yml/.json/.toml (max 40)", "total": total, "list": limited}

def grep_md(pattern):
    files = sorted(glob.glob(os.path.join(WS, "**/*.md"), recursive=True))
    matches = []
    for f in files:
        try:
            with open(f, "r", errors="replace") as fh:
                if pattern.lower() in fh.read().lower():
                    matches.append(f)
        except:
            pass
    return matches

def op3():
    m = grep_md("profile")
    return {"op": 3, "desc": "'profile' in .md files", "total": len(m), "list": m}

def op4():
    m = grep_md("playbook")
    return {"op": 4, "desc": "'playbook' in .md files", "total": len(m), "list": m}

def op5():
    a = set(grep_md("health.check"))
    b = set(grep_md("healthcheck"))
    c = set(grep_md("audit"))
    combined = sorted(a | b | c)
    return {"op": 5, "desc": "'health.check', 'healthcheck', or 'audit' in .md files", "total": len(combined), "list": combined}

def op6():
    entries = sorted(os.listdir(WS))
    details = []
    for e in entries:
        fp = os.path.join(WS, e)
        try:
            st = os.stat(fp)
            kind = "d" if os.path.isdir(fp) else "f"
            details.append({"name": e, "type": kind, "size": st.st_size})
        except:
            details.append({"name": e, "type": "?", "size": 0})
    return {"op": 6, "desc": "Top-level ls -la", "total": len(details), "entries": details}

results = [op1(), op2(), op3(), op4(), op5(), op6()]
print(json.dumps(results, indent=2))
