---
marp: true
paginate: true
footer: "KD3CCO · github.com/hatandspecs/keyboard-to-keyboard-cyberdeck"
style: |
  /* Plain white, one clear typeface, nothing decorative.
     Assertion-evidence: the headline is a full sentence making a claim and the
     body is the evidence for it. Carried inside this file rather than in a
     separate theme so the deck renders identically in the VS Code preview, in
     `marp` on the command line, and in an exported PDF, with nothing to
     register or configure first. */
  section {
    background: #ffffff;
    color: #111111;
    font-family: "Liberation Sans", Helvetica, Arial, sans-serif;
    font-size: 23px;
    line-height: 1.45;
    padding: 44px 56px 56px;
    /* The built-in theme wins on specificity for these, and its selectors are
       not ones a style block can match, so they are forced. The h1 color is a
       variable the theme exposes; the rest are not. */
    display: flex !important;
    flex-direction: column !important;
    justify-content: flex-start !important;
    --h1-color: #111111;
  }
  /* The assertion. A whole sentence, left aligned, never a category label. */
  section h1 { font-size: 32px; font-weight: 600; line-height: 1.25; margin: 0 0 20px 0; color: #111111 !important; }
  section h2 { font-size: 25px; font-weight: 600; margin: 0 0 12px 0; }
  section p { margin: 0 0 12px 0; }
  section ul { margin: 0 0 12px 0; padding-left: 26px; }
  section li { margin: 0 0 8px 0; }
  section strong { font-weight: 600; }
  section blockquote { margin: 0 0 16px 0; padding: 0 0 0 18px; border-left: 3px solid #cccccc; color: #222222; }
  section a { color: #0b4fa8; text-decoration: none; }
  section code { font-family: "Liberation Mono", Consolas, monospace; font-size: 0.86em; background: #f3f3f3; padding: 1px 5px; }
  section pre { background: #f6f6f6; border-left: 3px solid #cccccc; padding: 12px 16px; font-size: 17px; line-height: 1.45; margin: 0 0 14px 0; }
  section pre code { background: none; padding: 0; font-size: 17px; }
  /* Whatever the source image is, it fits the space that is left. */
  section img { display: block; margin: 0 auto; max-width: 100%; max-height: 430px; width: auto; height: auto; }
  section.evidence h1 { margin-bottom: 14px; }
  section.evidence img { max-height: 440px; }
  /* A slide whose evidence is a tall photograph: the picture is a panel down
     one side, so it is never scaled to a stamp to make it fit. */
  section.panel h1 { margin-bottom: 18px; }
  section.title, section.closing { justify-content: center !important; }
  section.title h1 { font-size: 42px; margin-bottom: 16px; }
  section.title p, section.closing p { font-size: 25px; color: #444444; }
  section .caption { display: block; font-size: 18px; color: #555555; margin-top: 10px; }
  /* Two pieces of evidence side by side, each with its own label. Sized by
     height so a tall photograph and a wide screenshot sit level, and so a
     replacement image of any shape still fits the slide. */
  section .pair { display: flex; gap: 30px; justify-content: center; align-items: flex-end; margin-top: 8px; }
  section .pair figure { margin: 0; text-align: center; }
  section .pair img { max-height: 232px; width: auto; margin: 0 0 6px 0; }
  section .pair figcaption { font-size: 17px; color: #555555; }
  section .trio img { max-height: 182px; }
  section footer { font-size: 14px; color: #888888; }
  section::after { font-size: 14px; color: #888888; }
---

<!-- _class: title -->
<!-- _paginate: false -->
<!-- _footer: "" -->

# A keyboard-to-keyboard cyberdeck

**KD3CCO**

A single-purpose HF text terminal for \$68

---

<!-- _class: evidence -->

# My desk is 20 by 14 inches, and a laptop does not fit on it

![](img/the-deck-on-the-desk.jpg)

<span class="caption">The whole station: the deck, a Bluetooth keyboard, and the FTX-1 just out of frame.</span>

---

# Every digital-mode program assumes a waterfall, a mouse, and forty windows

That is the right design for tuning and for contesting.

It is the wrong design for **having a conversation** — which is what RTTY, PSK31 and Olivia were built for, and the part I actually wanted.

Opening a laptop to operate also feels like clocking back in.

---

<!-- _class: evidence -->

# So the screen shows the conversation, and nothing else

![](../docs/screens/conversation-matrix.png)

<span class="caption">66 columns by 20 rows. A status line, the conversation, what you are typing, and the keys that do something.</span>

---

<!-- _class: evidence -->

# The first contact on it was RTTY, and it went exactly like any other QSO

![](img/first-rtty-qso-n3qe.jpg)

<span class="caption">N3QE: "FB DON I HAVE YOU AS NUMBER 1." Typed on the Bluetooth keyboard in the foreground.</span>

---

![bg right:38%](img/pi-behind-the-panel.jpg)

<!-- _class: panel -->

# It is a \$25 computer behind a \$43 panel, on standoffs that are also the stand

Raspberry Pi 3A+ · Waveshare 5-inch DSI panel · 66 × 20 characters of text.

It ran like this to begin with — the panel plugs into a ribbon cable, the standoffs hold it up, and nothing in the build is beyond a first-time solderer.

---

<!-- _class: evidence -->

# Standoffs are a stand. They are not a case

<div class="pair">
<figure><img src="img/shell-openscad-model.png"/><figcaption>drawn in OpenSCAD, around the real panel</figcaption></figure>
<figure><img src="img/shell-stl-render.png"/><figcaption>the shell it exports</figcaption></figure>
</div>

<span class="caption">Parametric, so the panel, the Pi and the standoff heights are numbers at the top of the file rather than measurements baked into a mesh — which matters when the thing you are modeling is already built and cannot change to suit the model.</span>

---

![bg right:36%](img/cased-deck-side-profile.jpg)

<!-- _class: panel -->

# Printed, it leans back like the thing it is pretending to be

It does two jobs. It **encloses the electronics** — the Pi, the back of the panel, and the ribbon cable between them, which was the most exposed thing on the bare build. And it is **a stable stand**, which four brass posts only approximated.

Vents down one side, a cutout for the cable, and the Pi still on the same standoffs — the shell goes **around** the existing build rather than replacing any of it.

Nothing inside changed. It is the same deck that worked before, now in something I can pick up with one hand.

**Twelve days** from the first contacts on this thing to a printed shell around it.

---

<!-- _class: evidence -->

# And it earns its place on the desk beside a radio twenty times its price

![](img/cased-deck-with-ftx1.jpg)

<span class="caption">Calling CQ on 20 m BPSK31. The FTX-1 does the radio; the deck does the conversation.</span>

---

# I did not write a modem, and that is the whole trick

A PSK31 demodulator that beats fldigi's would be a multi-year project, and I would lose.

```
  radio ──USB──► fldigi (headless, on a virtual screen nobody sees)
                    │
                    │ XML-RPC on the loopback interface
                    ▼
                 terminal  ──►  the panel
```

All of fldigi's signal processing. None of its interface.

---

<!-- _class: evidence -->

# Every control is one keystroke away, without leaving the conversation

![](../docs/screens/tuning.png)

<span class="caption">F2 tuning: carrier, AFC, squelch, signal search. F3 changes mode. Either key gets you back.</span>

---

<!-- _class: evidence -->

# Without a waterfall to look at, the deck has to hunt for the signal itself

![](img/signal-search-matrix.jpg)

<span class="caption">"search down: carrier 2059 → 1729 Hz." It steps the carrier looking for something above the squelch, because there is no picture to point at.</span>

---

<!-- _class: evidence -->

# It keeps up with an RTTY sprint exchange, which is the fastest thing I ask of it

![](img/rtty-sprint-exchange-k4zw.jpg)

<span class="caption">Serial number, name, state, sent and confirmed, in about 70 seconds on 80 m.</span>

---

<!-- _class: evidence -->

# The best test was explaining the deck to another operator, using the deck

![](img/explaining-the-deck-on-the-air.jpg)

<span class="caption">BPSK31 on 20 m: "i built this psk machine with a raspberry pi." KC3FL came back with a full station list — rig, beam, verticals, beverage.</span>

---

<!-- _class: evidence -->

# The color schemes are the one piece of pure indulgence, and worth every minute

![](img/color-schemes.png)

<span class="caption">Five schemes, switched from the menu. Amber is the readable one in daylight; matrix is the one people ask about.</span>

---

<!-- _class: evidence -->

# It pairs its own Bluetooth keyboard, with no second computer

![](../docs/screens/pairing-passkey.png)

<span class="caption">Pairing needs a screen and a keyboard that types. The deck has a screen; the keyboard being paired types.</span>

---

<!-- _class: evidence -->

# It joins a WiFi network from the panel, and keeps time without one

![](../docs/screens/wifi.png)

<span class="caption">A \$15 real-time clock means a field session is stamped correctly with the WiFi switched off.</span>

---

<!-- _class: evidence -->

# It has worked real DX — Martinique on 20 m PSK31, 20 watts

![](img/dx-qso-fm4ti-martinique.jpg)

<span class="caption">Also Germany, JO41XW — two operators in mountain villages, four thousand miles apart, typing at each other.</span>

---

<!-- _class: evidence -->

# An AI coding assistant reads your whole repository, and that changes which projects are worth starting

![width:880px](img/agent-loop.svg)

Hobby time arrives as confetti: twenty minutes before dinner, an hour on a Sunday. What decides whether a project happens is not the work in it — it is how much progress fits inside one of those fragments. A text terminal for HF with 534 tests behind it was never going to happen otherwise.

---

<!-- _class: evidence -->

# The gain is not just faster and better code — it is the practices the AI made affordable

![width:1000px](img/doc-first-cycle.svg)

<span class="caption">Interfaces, failure modes and what happens when a part is missing, all decided in the document before anything exists. 534 tests on this project, and they run with no radio attached — which is why it survived being put down for three weeks.</span>

---

# Its best trick is telling me what I did not know to ask

**Argue with it for an hour at two in the morning** without spending a friend's patience. In a solo hobby, that back-and-forth was the scarce ingredient.

**Then turn it against your own design.** I write down how I think something should work, and ask for an analysis of alternatives — and specifically: *does this design imply there are tools, techniques or facts out there that I am not accounting for?*

It is a retrieval system over what other people have already worked out. Use it as one.

---

<!-- _class: evidence -->

# Code, documentation, slides and the blog in one window, where the assistant can see all of it

![width:810px](img/vscode-workspace.png)

<span class="caption">Documentation is markdown in the repository, beside the code. Everything advances in the same sitting, so nothing drifts. The blog is another repository in the same workspace; these slides are markdown in this one.</span>

---

# The interesting part was never the code

**The bugs that cost the most lived in the gap between the bench and the real panel**, where an assistant cannot see: a radio whose CAT command was one digit short, so the display tracked the dial while every band change failed silently; and `Ctrl-Z` shipping dead on the console, because the terminal the tests run under defines that key differently. Every test passed.

**You do not need to start here.** Start with one annoyance in your own shack that you have stopped noticing because you have worked around it for a year.

---

<!-- _class: closing -->

# Build something that annoys you into existence

**Code, design document, runbook, operating tutorial**
github.com/hatandspecs/keyboard-to-keyboard-cyberdeck

**Write-up, with photographs and the things that went wrong**
hatandspecs.github.io/hamradio/articles/keyboard-to-keyboard-cyberdeck/

It runs on an ordinary laptop too: start fldigi, run one Python file.

**KD3CCO** — questions welcome
