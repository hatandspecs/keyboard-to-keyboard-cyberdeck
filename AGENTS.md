# AGENTS.md — keyboard-to-keyboard cyberdeck

A single-purpose HF text terminal: a Raspberry Pi 3A+ behind a 5-inch DSI panel,
66x20 characters, driving fldigi headless over XML-RPC. It also runs on an
ordinary laptop — start fldigi, run `./src/cyberdeck.py`, nothing else needed.

## Start here

| Read | For |
|---|---|
| `README.md` | What it is, what each file does, the test table |
| `docs/design_doc.md` | Numbered FR/NFR with honest status |
| `docs/` | Runbook and operating tutorial |
| `docs/screens/` | Rendered screenshots of every screen |

## Things that cost a lot to rediscover

- **Do not write signal processing.** fldigi does all of it; this program is a
  terminal that drives fldigi over XML-RPC on the loopback interface. A better
  PSK31 demodulator is not the project.
- **Run tests with `tools/run_tests.sh`, not pytest.** Each test file is a
  standalone script that prints its own checks and ends with `ALL PASS`.
  Invoking pytest on them wastes minutes and ends in `INTERNALERROR`.
- **fldigi must be running for the tests** — four of them drive the real
  program through a pseudo-terminal and read the screen back. No radio is
  needed, but a modem is.
- **The console font has no emoji.** Only glyphs already proven on the shipped
  panel are safe: `█ · ✓ ▸ ✗ ↑↓` and box drawing. Anything else renders as a
  blank or a replacement box, and you will not see it from here.
- **nmcli quirks** the WiFi screen depends on: it answers `enabled`/`disabled`
  but accepts `on`/`off`; `IN-USE` is empty in terse mode, so use `ACTIVE`; and
  it emits one row per access point, not per network.
- **polkit grants NetworkManager actions to an active local session.** A
  systemd service has no seat, so group membership such as `netdev` changes
  nothing — the rule file is what matters.
- **Startup order matters.** Restoring the saved mode sits behind an
  `if self.fldigi.connected` guard, and `_persist_settled` must not write
  before `_startup_done`, or a cold boot silently overwrites the saved mode
  with CW. There are tests for exactly this; run them before touching startup.

## Where it stands

534 tests, all passing. The deck has worked real DX on PSK31 and RTTY. A DS3231
real-time clock is fitted and verified across a power cut with NTP disabled. The
WiFi screen joins networks from the panel. A UPS HAT is on order for graceful
shutdown.

Reach the deck over ssh when I ask for it — the address is in the runbook.

## How I work — standing preferences

These are the same in every repository of mine. They are restated in each one
so that any assistant reads them, not only the one configured on my machine.

**Git is mine.** Never run `git commit` or `git push`, in any repository, for
any reason. Reading history is encouraged — `log`, `diff`, `status`, `show` —
and so is telling me when a good commit point has been reached, or drafting a
commit message for me to use. Finish the work, leave it uncommitted, and say
what changed and where.

**Hardware is mine.** Do not build SD-card images, `rsync` to a device, open an
`ssh` session to one, or run anything on a Raspberry Pi or the cyberdeck unless
I ask in that message. Hand me the exact commands to copy and paste — one block
per step, in order — say what each should print, and stop. I will run them and
paste the output back. Local work in the repository needs no such restraint.

**Writing.** No British spellings; US throughout. Design documents are
declarative: no hero's-journey narrative, no second-person "you", and never
state something as fact and then refute it a few lines later. For an article
already published, add a dated update section rather than rewriting the
narrative — the wrong turns are part of why it is worth reading. Do not repeat
a warning I have already acknowledged.

**Images.** Look at any photograph or screenshot before adding it to an
article, a slide deck, or a repository. Phone numbers show up in radio screens
and log captures, coordinates show up in beacon lines and station pages, and
backgrounds show rooms. Say what you found and redact it rather than guess.

**Destructive commands.** `/dev/sdX` stays a placeholder in any flashing or
disk-writing instructions. Never substitute a real device node.

**Amateur radio.** Test traffic uses my own callsign and its SSIDs — never
another operator's call, unless I explicitly ask for one.

**Working style.** I start fresh sessions often rather than carrying one for
weeks, so assume no memory of previous conversations. Everything you need
should be in this file or in the documents it points at.

**Keeping this file true is part of the work.** Anything dated here records
what was true on that date, not what is true now — check it against the
repository before relying on it, and correct it when it is wrong. When a
session has changed how the project works, turned up a gotcha worth the next
session not rediscovering, or outdated something in a "where it stands"
section, propose the edit to this file before the session ends. Do not wait to
be asked, and do not save it for a tidy-up later: the next session starts cold,
and this file is most of what it gets.
