# Read-only host audit

Run from the isolated planning worktree over SSH. Read only. Do not install, restart, reload, enable, disable, deploy, edit secrets or change runtime state.

Record evidence in CURRENT_ENGINEERING_REALITY.md.

## Repository identity

```bash
pwd
git status --short --branch
git rev-parse HEAD
git branch --show-current
git remote -v
git worktree list
git log -1 --oneline --decorate
```

## Production/trunk references

Only if paths exist and are safe to read:

```bash
git -C /srv/clive-engineering/repo rev-parse HEAD 2>/dev/null || true
git -C /opt/crooks-os rev-parse HEAD 2>/dev/null || true
git -C /opt/clive rev-parse HEAD 2>/dev/null || true
```

Never checkout/pull/reset those paths.

## Toolchain

```bash
command -v claude || true
claude --version 2>/dev/null || true
claude auth status 2>/dev/null || true
node --version 2>/dev/null || true
npm --version 2>/dev/null || true
python3 --version
```

Never print token files, API keys or environment secrets.

## Engineering processes/services

```bash
systemctl --no-pager --full list-units --type=service | grep -Ei 'clive|crooks|engineer|worker' || true
ps -eo pid,ppid,etimes,%cpu,%mem,cmd --sort=-%mem | grep -Ei 'engineering_dispatcher|remote_engineering|claude' | head -40
```

For a relevant service, only:
```bash
systemctl --no-pager --full status <service>
systemctl cat <service>
```

## Resource envelope

```bash
nproc
free -h
df -h
uptime
ulimit -a
```

If this is not the worker host, say so. Do not infer worker capacity from production.

## Browser capability

```bash
command -v chromium || command -v chromium-browser || command -v google-chrome || true
find /usr /opt -maxdepth 4 -type f \( -name chromium -o -name chrome -o -name google-chrome \) 2>/dev/null | head -20
```

Do not install anything.

## Dispatcher/runtime facts to capture
- max concurrency;
- repair limit;
- reviewer selection;
- worker CLI path/version;
- browser paths;
- state/runtime path;
- landing setting;
- queue counts if an existing read-only status path exposes them.

For every fact record value, source/command, timestamp, confidence and BUILT/ACTIVE/PROVEN/GAP/UNKNOWN status. Absence of evidence is not evidence of absence.
