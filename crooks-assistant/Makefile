VENV := .venv
PY   := $(VENV)/bin/python
# 3.12 preferred; 3.11 is what the suite was verified on. Anything older will not work.
PYTHON ?= $(shell command -v python3.12 || command -v python3.11 || command -v python3)
PIP  := $(VENV)/bin/pip

# Which supervisor this machine has. The targets below are the same words on both — `make
# install`, `make status`, `make restart` — and only what sits behind them differs, so the
# steps written down in the README and in docs/DEPLOY_LINUX.md are one set of steps.
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Linux)
INSTALLER := scripts/install_systemd.py
LOGS      := journalctl -u crooks-assistant -f -n 40
SECRETS   := scripts/provision_secrets.py --all
else
INSTALLER := scripts/install_launchd.py
LOGS      := tail -n 40 -F logs/assistant.out.log logs/assistant.err.log logs/whisper.out.log logs/whisper.err.log
SECRETS   := scripts/set_secrets.py --all
endif

.PHONY: help doctor venv up install uninstall status restart logs health dev bench test test-live experience experience-ui experience-live experience-list screens matrix tool-matrix lint chat acceptance accept write-check whisper-server secrets shopify gmail gmail-verify voice check test-session-start test-session-status test-session-stop test-session-report test-session-proposals record-start record-status record-stop record-list record-save-test bench-intelligence bench-lanes commands commands-remove update watch control control-app

help:
	@echo "The steps you take, in order. Every one is: open Terminal, cd into this folder, type the line."
	@echo ""
	@echo "First time on this Mac:"
	@echo "  make doctor          check the Mac has everything; prints the fix for anything missing"
	@echo "  make venv            install the Python side (once)"
	@echo "  make secrets         store the Shopify credentials and the ElevenLabs key (asks for each)"
	@echo "  make shopify         prove Shopify works and the token cache is used"
	@echo "  make gmail           authorise Gmail once, in a browser"
	@echo "  make test            prove it works here (~6 s, entirely offline)"
	@echo "  make test-live       the two tests that touch the real store and inbox (needs credentials)"
	@echo ""
	@echo "Every day:"
	@echo "  make up              run everything in this one window: backend, speech, HTTPS route"
	@echo "  make install         or: have the Mac start it all at login, no window at all"
	@echo "  make status          is it running, what /health says, the address for the tablet"
	@echo "  make restart         restart the login-time services (after a git pull)"
	@echo "  make uninstall       stop and remove the login-time services"
	@echo "  make logs            follow the login-time services' output"
	@echo ""
	@echo "When something needs looking at:"
	@echo "  make health          is it well: one line and an exit code (V=1 every check)"
	@echo "  make check           doctor + shopify + gmail-verify in one go"
	@echo "  make gmail-verify    prove Gmail refreshes without a browser"
	@echo "  make write-check     rehearse one change through the engine: TOOL=… ARGS='{json}' [COMMIT=1]"
	@echo "  make voice           hear the voice on this Mac (one short ElevenLabs request)"
	@echo "  make chat            ask questions by typing (cheaper than the tablet)"
	@echo "  make acceptance      the 18-command Day 1 test; add SPOKEN=1 to score spoken runs"
	@echo "  make accept          everything provable without the store: lint, Node, pytest, a server, latency, the page in Chromium"
	@echo ""
	@echo "The experience suite — real turns against a golden shop, and the page in a browser:"
	@echo "  make experience      the golden scenarios; writes reports/experience/<run>/"
	@echo "  make experience-ui   the same, and drives the page in Chromium for screenshots"
	@echo "  make experience-live the same questions against the REAL shop and inbox, read-only"
	@echo "  make experience-list what there is to run    (SCENARIO=back runs one)"
	@echo "  make screens         §32's 34 named surfaces into docs/screens/phase5/ (a shot whose surface is missing is written .MISSING.png)"
	@echo "  make matrix          which operations are reachable by voice, by touch, and tested"
	@echo "  make tool-matrix     every tool and intent family audited; writes docs/phase4/TOOL_MATRIX.md"
	@echo "  make dev             the backend alone, with auto-reload, for working on the code"
	@echo "  make whisper-server  speech recognition alone (prints build steps if not built yet)"
	@echo "  make bench           choose the Whisper model from your tablet recordings"
	@echo "  make lint            code style"
	@echo ""
	@echo "An hour with the tablet, written down (nothing restarts; the page joins within a poll):"
	@echo "  make test-session-start [NAME='first hour']   begin; prints the session id"
	@echo "  make test-session-status                      what is running, events so far"
	@echo "  make test-session-stop                        end it"
	@echo "  make test-session-report [SESSION=ts-…]       write reports/<session>.md from logs/test-sessions/<session>.jsonl"
	@echo "  make test-session-proposals [SESSION=ts-…]    write reports/<session>-proposals.md: improvement candidates, cited by turn, never applied"
	@echo ""
	@echo "Real use, written down and minimised (NOT a test session; needs CROOKS_RECORD_EXPERIENCE=true):"
	@echo "  make record-start [NAME='thursday pm']        begin a recording; prints its id"
	@echo "  make record-status                            what is recording, events so far"
	@echo "  make record-stop                              end it"
	@echo "  make record-list [RECORDING=rec-…]            the interactions in a recording, one line each"
	@echo "  make record-save-test [RECORDING=… TURN=…]    save one interaction as a fixture and a manifest"
	@echo ""
	@echo "  make bench-intelligence                       time the read layer, the working sets and batch staging against a fake store"
	@echo "  make bench-lanes                              time the fast lane against the 9 September session's own figures"
	@echo "  make watch [SESSION=ts-…] [V=1]               follow what it is doing, live, one line per thing (V=1 for everything)"
	@echo ""
	@echo "Three words on the PATH, so none of this needs a folder or a make:"
	@echo "  make commands        install crooks-update, crooks-status and crooks-watch into ~/.local/bin"
	@echo "  crooks-update        pull, install what changed, restart, verify — fast-forward only, never destructive"
	@echo "  crooks-status        one screen: build, voice, Claude, Shopify, Gmail, orders, the tablet's address"
	@echo "  crooks-watch         the live trace"
	@echo "  make commands-remove take them off again"
	@echo ""
	@echo "CROOKS Control — the menu bar instead of Terminal (macOS 13 or later):"
	@echo "  make control-app     build the app and put it in /Applications; then open it"
	@echo "  make control         what the app shows, as JSON  (WHAT=status|plan|apply|rollback|mark-good|actions|contract)"
	@echo "  crooks-control       the same command, on the PATH after make commands"

doctor:
	@$(PY) scripts/doctor.py 2>/dev/null || python3 scripts/doctor.py

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -e ".[dev]"
	@echo "venv ready."

up:
	$(PY) scripts/up.py

install:
	$(PY) $(INSTALLER)

uninstall:
	$(PY) $(INSTALLER) --uninstall

status:
	$(PY) $(INSTALLER) --status

restart:
	$(PY) $(INSTALLER) --restart

logs:
	$(LOGS)

health:
	@$(PY) scripts/healthcheck.py $(if $(V),-v,) $(if $(JSON),--json,)

dev:
	$(PY) -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

whisper-server:
	$(PY) scripts/whisper_server.py

bench:
	$(PY) scripts/bench_whisper.py

test:
	$(VENV)/bin/pytest -q -m "not live"

test-live:
	$(VENV)/bin/pytest -q -m live

lint:
	$(VENV)/bin/ruff check app config scripts tests

chat:
	$(PY) scripts/chat.py

acceptance:
	$(PY) scripts/acceptance.py $(if $(SPOKEN),--spoken,)

write-check:
	$(PY) scripts/write_check.py $(TOOL) '$(ARGS)' $(if $(COMMIT),--commit,)

test-session-start:
	$(PY) scripts/test_session.py start --name "$(if $(NAME),$(NAME),session)"

test-session-status:
	$(PY) scripts/test_session.py status

test-session-stop:
	$(PY) scripts/test_session.py stop

test-session-report:
	$(PY) scripts/test_session.py report $(SESSION)

test-session-proposals:
	$(PY) scripts/test_session.py proposals $(SESSION)

record-start:
	$(PY) scripts/record.py start --name "$(if $(NAME),$(NAME),recording)"

record-status:
	$(PY) scripts/record.py status

record-stop:
	$(PY) scripts/record.py stop

record-list:
	$(PY) scripts/record.py list $(RECORDING)

record-save-test:
	$(PY) scripts/record.py save-test $(RECORDING) $(if $(TURN),--turn $(TURN),)

commands:
	@$(PY) scripts/install_commands.py

commands-remove:
	@$(PY) scripts/install_commands.py --remove

update:
	@$(PY) scripts/update.py $(if $(CHECK),--check,) $(if $(TEST),--test,) $(if $(JSON),--json,)

control:
	@$(PY) scripts/control.py $(if $(WHAT),$(WHAT),status) $(if $(YES),--yes,)

control-app:
	@sh mac/CrooksControl/build.sh --install

watch:
	@$(PY) scripts/watch.py $(SESSION) $(if $(V),--verbose,)

bench-lanes:
	@$(PY) scripts/bench_lanes.py $(if $(ORDERS),--orders $(ORDERS),) $(if $(LATENCY),--latency-ms $(LATENCY),)

bench-intelligence:
	$(PY) scripts/bench_intelligence.py

accept:
	$(PY) scripts/accept.py $(if $(SHOTS),--shots $(SHOTS),) $(if $(NO_BROWSER),--no-browser,)

experience:
	$(PY) scripts/experience.py $(if $(SCENARIO),--scenario $(SCENARIO),)

experience-ui:
	$(PY) scripts/experience.py --ui $(if $(SCENARIO),--scenario $(SCENARIO),)

experience-live:
	$(PY) scripts/experience.py --live $(if $(SCENARIO),--scenario $(SCENARIO),)

experience-list:
	@$(PY) scripts/experience.py --list

# §32's screenshot matrix. Its own target rather than a flag on experience-ui: these files are
# named and numbered and read as a set, and a shot whose surface does not exist yet is written
# as `…MISSING.png` so a directory listing is itself the report.
screens:
	@$(PY) -c "import asyncio;from experience.browser import capture_matrix;p=asyncio.run(capture_matrix());m=p.get('missing') or [];print(f\"{len(p.get('shots') or [])} shots written, {len(m)} surface(s) missing\");[print('  MISSING '+x['id']+' '+x['name']+': '+x['why']+((' ['+x['owner']+']') if x.get('owner') else '')) for x in m]"

matrix:
	@$(PY) -c "import sys; sys.path.insert(0,'.'); from experience.matrix import markdown; print(markdown())"

tool-matrix:
	@$(PY) -c "import sys; sys.path.insert(0,'.'); from experience import tool_matrix; print(tool_matrix.write())"

secrets:
	$(PY) $(SECRETS)

shopify:
	$(PY) scripts/shopify_check.py

gmail:
	$(PY) scripts/gmail_auth.py

gmail-verify:
	$(PY) scripts/gmail_auth.py --verify

voice:
	$(PY) scripts/voice_check.py

check: doctor shopify gmail-verify
