# Review — code-diff (delivery/Winston lens) — presentation/storyboard.md

Mode: storyboard delivery + MIT "How to Speak" compliance
Scope read: presentation/storyboard.md (full), presentation/research/how-to-speak.md (full)
Disposition log considered: n/a (no prior disposition log for this artifact)

Method note for pacing: I estimate realistic Ukrainian academic delivery at ~2.0 words/sec
(≈120 wpm). Ukrainian is morphologically heavy (longer words, fewer per second than English),
and a nervous defense candidate under a clock tends to *speed up*, but the content here is
technically dense (must be said carefully, not skimmed), which pulls the effective rate back
down. For dense technical narration with terms like "проміжний JWT", "Argon2id", "wg set wg0
peer" the realistic rate is closer to 1.8 w/s because the speaker must enunciate identifiers.
I derive each slide's word load from the narration the slide *forces* (notes + the spoken
context the slide implies), not from on-slide text.

---

## Blockers

- **Slide 5 budget (65 s) cannot carry the 7-step flow + framing it claims** — anchor: storyboard.md § Слайд 5 (lines 166–186)
  - Issue: The presenter must narrate a 7-step two-leg sequence AND speak two side-panel
    facts (Fernet-at-rest, JWT=HS256, RFC 6238) AND verbally mention registration ("реєстрацію
    згадати вербально") AND deliver the "Реп. 2" cycle line AND the note's emphasis about the
    intermediate token being TOTP-only / 403-on-bypass. Counting only what must be spoken to
    make the sequence intelligible: each of the 7 steps needs a real clause (endpoint + what
    happens + what returns) — realistically ~12–18 words/step = ~100 words for the steps alone,
    plus ~30 words of framing (registration aside, intermediate-token-scope point) plus the
    cycle line (~15 words). That is ~145 words. At 1.8 w/s (dense identifiers) = **~80 s**, at
    2.0 w/s = **72 s**. Both exceed the 65 s budget, and that assumes zero stumbling on a live
    sequence diagram. This is the single most likely place the talk overruns.
  - Required action: Re-budget slide 5 to **75–80 s** and pull the time from elsewhere (see
    realistic-total below), OR explicitly cut narration: drop the spoken side-panel facts
    (Fernet/HKDF/HS256 are Q&A-only material, not main-line narration) and collapse steps to
    the 4 load-bearing beats: (1) пароль→проміжний токен, (2) TOTP→повний токен, (3) сесія→
    `wg set wg0 peer`, (4) тунель. The note itself already over-loads the slide; make the cut
    explicit in the storyboard so the presenter doesn't try to say all of it.

- **Realistic total exceeds the 4:30 claim and risks breaching 5:00** — anchor: storyboard.md § Таблиця хронометражу (lines 60–74)
  - Issue: Per-slide realistic estimates (at 1.8–2.0 w/s, dense content):
    - S1 Title (10 s): the SLOGAN promise (lines 17–19) is ~40 spoken words = **~20 s**, not 10 s.
      10 s is impossible while also naming the university/title context. Budget is ~2× short.
    - S2 Problem (40 s): two-track contrast + "ключ ≠ людина" + 4 consequences + the note's
      "свідоме рішення / ~4000 LOC / compromised-laptop / SOC2/ISO" framing ≈ 90–100 words →
      **~48 s**. Slightly over.
    - S3 Competitors (40 s): explaining a 4×6 matrix verbally (selection criteria + why DefGuard
      is nearest + "no peer-reviewed systematic approach") ≈ 90 words → **~46 s**. Over.
    - S4 Idea (40 s): the full thesis rep + add/remove subprocess + DefGuard contrast ≈ 85 words
      → **~43 s**. Slightly over.
    - S5: **~75 s** realistic (see blocker above) vs 65 budgeted.
    - S6 Results (50 s): two-panel chart narration + the defensive trade-off framing + CPU-from-
      Docker caveat ≈ 95–105 words → **~52 s**. Roughly on or slightly over.
    - S7 Contributions (25 s): 4 past-tense items spoken in full (lines 222–225 are long
      sentences — item 2 alone is ~25 words) + salute ≈ 75 words → **~38 s**, not 25 s.
    - **Realistic sum ≈ 20+48+46+43+75+52+38 = 322 s ≈ 5:22.** That is over the hard 5:00 cap,
      not the stated 4:30. The stated table undercounts the title and the contributions slide
      most severely, and slide 5 moderately.
  - Required action: Either (a) rebuild the budget honestly toward ~4:50 with a real plan to
    finish under 5:00, trimming narration (notably: shorten S7 items to telegraphic phrases the
    presenter expands minimally; cut S5 side-panel narration; tighten S1 promise to ~25 words),
    or (b) accept the deck is a ~5:30 talk and cut a slide / merge S2+S3. The current "270 s /
    4:30 with a 10 s buffer for a 7-second Q&A pause" is not achievable as written — the
    7-second wait-after-question (note line 73) would push to ~5:30+. Recommend dropping the
    planned in-talk 7-second-question device entirely for a 5-minute hard cap.

---

## Important

- **Title slide promise is too long to land in 10 s and the slogan is borderline two ideas** — anchor: storyboard.md lines 16–20, 89
  - Issue: The promise (lines 17–19) packs "compulsory 2FA + over unmodified WireGuard + no
    protocol change + no PSK + session-exists-as-interface-node" — that is the whole thesis in
    one breath. As a 10 s opener it will be rushed and the audience won't catch it. Winston's
    promise should be *one* crisp empowerment statement.
  - Suggested fix: Lead with the short anchor form only (line 20: «Сесія як вузол: 2FA без
    зміни протоколу і без PSK») as the spoken promise, ~12–15 words, and let the long form
    unfold across S4. Re-budget S1 to ~15 s. This both fixes pacing and sharpens the promise.

- **Slide 3 matrix (4×6 ✓/✗) is at real risk of failing the "minimal words / one dense slide" rule** — anchor: storyboard.md lines 119–137, and § hapax (line 53)
  - Issue: The deck declares S5 as the ONE dense slide. But a 4-row × 6-column comparison
    matrix with row labels like "Незалежність від зовнішнього IdP" and "Управління ключами"
    plus a callout is itself dense and word-heavy when built — it is a *second* complex slide
    in practice, violating the hapax-legomenon rule. A committee reading a 24-cell matrix will
    be in "read mode," not "listen mode."
  - Suggested fix: Reduce to the fence that actually matters: a 2-column contrast (DefGuard vs
    Наша система) on the one differentiating axis ("стандартний клієнт / без PSK-токена"), or a
    single row of ✗ for the field and one ✓ row for "Наша система." Keep the full 5-system
    matrix as a Q&A backup slide. This restores "one idea per slide" and protects the single-
    dense-slide rule.

- **Slide 6 two-panel chart is borderline two ideas on one slide** — anchor: storyboard.md lines 190–207
  - Issue: Left panel (data-plane parity, 2–3 bar pairs) + right panel (control-plane onboarding
    cost) is genuinely *two* messages ("parity" and "the cost is one-time"). The stated single
    idea (line 191) tries to bind them, but two charts side-by-side read as two ideas and add
    visual density. Combined with the S3 matrix, the deck now has S3+S5+S6 all trending dense.
  - Suggested fix: This is defensible because the contrast (zero data-plane cost vs one-time
    control-plane cost) IS the surprise and is the honest-trade-off story. Keep it, but make the
    left panel the dominant visual and reduce the right panel to a single annotated 92→1571 bar
    with the one-word label "одноразово." Drop the optional p95 latency pair (line 198) to cut
    clutter. Ensure on-slide numbers don't turn into the two sentences shown at lines 205–206.

- **On-slide text on S2 and S6 risks exceeding "minimal words" when built** — anchor: lines 106–110, 204–206
  - Issue: S2 on-slide text lists "IPsec / OpenVPN → EAP / RADIUS / LDAP", "WireGuard → лише
    ключ", "ключ ≠ людина", and four ✗ phrases — that is ~18–20 words plus a diagram, near the
    20-word ceiling. S6's on-slide lines (205–206) are effectively two full sentences with
    numbers and parentheticals — likely >20 words and reads like prose.
  - Suggested fix: For S6, reduce to numerals + one anchor phrase: "890→881 (1%)", "917=917
    (0%)", "той самий wireguard.ko"; move "одноразово, площина керування" into the chart callout
    only. For S2, drop "лише ключ" (redundant with the diagram) and keep the four ✗ as icons,
    not text+icon.

- **Cycle repetition 3–4 is conceptually thin between S5 and S6** — anchor: storyboard.md lines 46–47
  - Issue: Rep.2 (S5: "wg set wg0 peer adds the node") and Rep.3 (S6: "data plane = same
    wireguard.ko because protocol unchanged") are good *different angles*. The risk is the
    presenter reciting near-identical phrasing ("протокол не змінено") three times in 90 seconds,
    which reads as repetitive rather than as cycling-from-new-angles (the dull-repetition failure
    Winston warns against). The table is fine on paper; the delivery risk is real.
  - Suggested fix: Add a one-line *phrasing* differentiator per rep in the notes so the presenter
    varies words, not just angle: S5 "механічно — два виклики subprocess", S6 "тому й вимірюється
    нуль". This is a notes-level fix, not a structural one.

## Nits

- **Verbal-punctuation line enumerates 5 items, slightly long for a landmark** — anchor: line 51
  - The landmark (lines 50–51) recaps problem+competitors+idea then previews works+cost — that's
    a clean "first…now…" but it's ~25 words mid-talk. Fine, but trim to "Ми побачили проблему,
    конкурентів і нашу ідею — тепер як це працює і скільки коштує." Placement (end S4 → start S5)
    is correct per Winston (~halfway).

- **"Дякую"/"Питання?" prohibition is correctly observed** — anchor: lines 218, 228, 241
  - Confirmed compliant: final slide is Contributions (past tense, 4 items), stays up for Q&A
    (line 229, heckler-proofing), close is a salute with no "thank you." This is correct.

- **Promise-as-empowerment is correct, not a joke** — anchor: lines 81, 91
  - Confirmed: opening is a concrete capability promise, no joke, no "thank you for the
    opportunity." Compliant. Only issue is length (see Important above), not kind.

- **Fence is built early and against the named nearest competitor (DefGuard)** — anchor: lines 44, 134
  - Confirmed compliant: negative-definition fence at S3 vs DefGuard ("без PSK-токена, без
    власного клієнта") and reinforced S4. Good.

- **1571 vs 92 discrepancy flag is good practice** — anchor: lines 212–213
  - The storyboard correctly flags the conclusions.tex/table mismatch and picks the table number
    for the spoken line. No change needed; just ensure the built slide and the thesis don't
    contradict on the same screen.

## Notes

- Winston-rule compliance is genuinely strong on structure: promise (kind), fence, cycle
  scaffolding, salute close, no laser pointer (baked callouts), no title bars. The failures are
  almost entirely in **pacing realism** and **creeping density** (S3 matrix + S6 two-panel),
  not in conceptual structure.
- The single biggest risk to a clean defense is the clock: as written this is a ~5:20 talk sold
  as 4:30. Under defense pressure the candidate will either rush S5 (the dense slide, worst place
  to rush) or run past 5:00. Fix the budget honestly before building slides.
- The "ask a question, wait 7 s" device (lines 73–74) is incompatible with a hard 5:00 cap given
  the realistic runtime; recommend reserving it only if a generous time slot is confirmed.

---

**Verdict:** Structurally Winston-compliant (promise, fence, cycle, salute, no-laser all correct),
but the 4:30 timetable is unrealistic — realistic runtime is ~5:20, with slide 5 under-budgeted
and slides 3/6 creeping toward a second and third dense slide; re-budget honestly and trim before
the deck is built.
