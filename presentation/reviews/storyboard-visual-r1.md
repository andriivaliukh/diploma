# Review — code-diff (visual-design lens) — presentation/storyboard.md

Mode: code-diff (storyboard / visual-design + legibility lens)
Scope read: presentation/storyboard.md (full), presentation/research/how-to-speak.md (full)
Disposition log considered: n/a (no prior disposition log for this artifact)

Lens: visual feasibility, projector legibility from the back of the room, font ≥40pt
rule, colorblind/projector contrast, cross-slide motif coherence, Beamer ornament
strip. Numbers and rhetorical structure are out of my lens (owned by content/facts
review); I touch them only where they drive a visual/legibility problem.

---

## Blockers

- **Slide 5 sequence diagram: too dense to read in 65 s from the back; same overlap risk that hit thesis p.25** — anchor: `storyboard.md § Слайд 5` (lines 166–186)
  - Issue: The spec packs 3 lifelines × 7 numbered steps × 3 side-plates (`TOTP=RFC 6238`, `Fernet`, `JWT=HS256`) × a baked callout, plus arrow labels carrying endpoint paths AND TTLs AND scopes (`POST /auth/totp/verify`, `Bearer проміжний токен`, `TTL 5 хв scope totp_verify`, etc.). That is ~7 long monospace arrow labels stacked vertically on a 4:3 slide. To fit, the labels WILL drop below 40pt — and worse, this is exactly the label-overlap failure the thesis original had on p.25. The storyboard even self-identifies this as the single hapax-legomenon slide, which justifies *one* dense slide but not an *illegible* one.
  - Required action: (a) Cut the 3 side-plates from the slide entirely — speak `RFC 6238 / Fernet / HS256` in notes; they are not part of the critical path and are the first thing a back-row viewer cannot read. (b) Shorten arrow labels to ≤3 tokens: e.g. step 1 label = `login (пароль)`, not the full JSON/endpoint; put the verb, not the route. (c) Keep at most the two TTL annotations (`5 хв`, `24 год`) as they carry the security point. (d) Collapse steps 5–6 into one round-trip arrow pair so the diagram is 5 visible exchanges, not 7. Target: every glyph ≥40pt-equivalent at projection size, max one monospace token per arrow.

- **Slide 3 matrix is 4×6 with two-word row headers and a highlighted column — at risk of <40pt and dense ✓/✗ field** — anchor: `storyboard.md § Слайд 3` (lines 119–138)
  - Issue: Header says "4 рядки × 5 стовпців" (line 121) but the column list enumerates 6 (DefGuard, Firezone, NetBird, Tailscale/Headscale, WAG, Наша система) — that is a 4×6 = 24-cell grid plus a header row and a header column. Row labels are full phrases ("Незалежність від зовнішнього IdP", "Стандартний WG-клієнт") which on a 6-column grid leave very little horizontal room; the cell font and the row-header font will be forced well below 40pt to fit 6 columns of marks. "Tailscale/Headscale" as a single column header is also a long string.
  - Required action: (a) Fix the row/column count mismatch in the spec (it is 6 data columns). (b) Drop to **4 columns**: keep the nearest competitor **DefGuard**, one OIDC-dependent representative (e.g. **Tailscale**), **WAG**, and **Наша система**; mention Firezone/NetBird verbally as "and the same OIDC-IdP limitation applies to Firezone and NetBird." A 4×4 grid is the legibility ceiling for a back-row ✓/✗ matrix at 40pt. (c) Replace full-sentence row headers with 1–2 word labels: "WG-клієнт", "Без IdP", "Власний TOTP", "Ключі". Speak the full requirement.

- **Color-only encoding of ✓/✗ and add/remove arrows fails colorblind + projector contrast** — anchor: `storyboard.md § Слайд 3` (line 110, 132), `§ Слайд 4` (lines 149–151), `§ Слайд 6` (callout, line 202)
  - Issue: Red ✗ / green ✓ (slide 3) and green add-arrow / grey-or-dashed remove-arrow (slide 4) lean on the red–green channel, which ~8% of men (a likely demographic on an older committee) cannot separate, and which washes out badly on a typical lecture-hall projector. If color is the *only* differentiator, the matrix and the symbol motif become ambiguous.
  - Required action: Make the encoding redundant with **shape/glyph**, not color: ✓ = bold check glyph, ✗ = bold cross glyph (legible in monochrome); the green/red is then only reinforcement. For slide 4 add/remove, use **solid line + filled node** vs **dashed line + hollow/grey node** (line style is the carrier, color secondary). Confirm every distinction survives a grayscale print test.

---

## Should-fix

- **Slide 6 two-panel chart risks splitting attention and crowding callouts** — anchor: `storyboard.md § Слайд 6` (lines 190–213)
  - Issue: Left panel = 2–3 bar pairs (tcp_t, tcp_p, optional p95 latency) + big anchor caption; right panel = 1 bar pair (92→1571) + a long baked callout ("одноразова 2FA-церемонія, НЕ постійні витрати; у потоці трафіку — нуль додаткової затримки"). That callout is a full sentence (line 202) and will not hold 40pt. Two panels on one 4:3 slide also halves the width available to each, shrinking bar labels.
  - Suggested fix: (a) Drop the optional p95 latency pair (line 198) to keep the left panel to 2 clean pairs. (b) Shorten the right-panel callout to a 3-word baked label, e.g. **«одноразово, не постійно»**, and speak the rest. (c) Resolve open question #3 (line 248) toward **no OpenVPN column** — adding a third comparator overcrowds an already two-panel slide. (d) Ensure the per-bar value labels (890, 881, etc.) are the largest text after the anchor caption.

- **`wg set wg0 peer …` monospace command shown verbatim on slides 4 and 5 — long monospace strings are the worst case for 40pt + back-row legibility** — anchor: `storyboard.md § Слайд 4` (lines 150–151), `§ Слайд 5` (line 175)
  - Issue: Full commands like `wg set wg0 peer <pubkey> allowed-ips <ip>/32` are ~45 chars of monospace; at 40pt that overflows a 4:3 content width, and shrinking monospace is exactly what kills back-row legibility. The command is load-bearing for the "two subprocess calls" point, but the full argument list is not.
  - Suggested fix: Show the **shape** of the command, not the args: `wg set wg0 peer …` (add) and `… peer … remove` (remove). The `<pubkey>`/`allowed-ips` detail goes in speaker notes. This also strengthens the symbol motif (two short mirrored commands read as a pair).

- **Symbol motif solid-vs-dashed node must be specified with high-contrast line weights, or it will not read on a projector** — anchor: `storyboard.md § SYMBOL` (lines 22–26), `§ Слайд 4` (lines 148–151)
  - Issue: The "appearing solid node / disappearing dashed-grey node" motif is good and reusable, but "сірий" (grey) on a low-contrast projector can vanish entirely, and a thin dashed outline reads as "smudge," not "removed." The motif appears on slides 4/5/6/7 so an unreadable version is a recurring defect.
  - Suggested fix: Standardize the motif as a TikZ style pair: present-node = **thick solid black outline, light fill**; gone-node = **thick dashed outline, no fill, ~60% grey** (not lighter). Keep the `wg0` bus line a single consistent weight across all four slides. Define both as named TikZ styles (`\tikzset{wgpeer/.style=…, wggone/.style=…}`) so slides 4/5/6/7 are pixel-consistent — this directly serves your CONSISTENCY requirement.

- **Slide 2 has 4 ✗-list items + a two-track diagram + a callout — close to two ideas, and the ✗ row repeats slide 3's encoding** — anchor: `storyboard.md § Слайд 2` (lines 95–115)
  - Issue: The two contrast tracks (IPsec/OpenVPN vs WireGuard) plus a right-hand vertical 4-item ✗ list plus the "ключ ≠ людина" callout is a lot for a single-idea 40s slide, and the 4 cross-items ("немає 2FA / відкликання / журналу / особи") pre-empt slide 3's matrix rows.
  - Suggested fix: Keep the two-track diagram + the single "ключ ≠ людина" callout as the whole visual. Drop the 4-item ✗ list (it duplicates slide 3 and adds text); speak those four gaps as the verbal bridge into slide 3. Keeps slide 2 to one idea and one diagram.

## Nits

- **Optional title-page motif could clutter a conservative title** — anchor: `storyboard.md § Слайд 1` (lines 82–83) — for an older committee, a clean typeset title is safest; if you keep the wg0+lock motif, make it a single faint hairline at the very bottom, well clear of the institution/title text. Easy to over-do; default to omitting it.
- **Anchor captions ("Той самий `wireguard.ko`", "Без зміни протоколу. Без PSK.") mix monospace and prose** — anchor: `storyboard.md § Слайд 4` (line 152), `§ Слайд 6` (line 199) — fine, but set the monospace token in the *same point size* as the surrounding prose (XeLaTeX monospace often renders visually smaller); pick a mono font with a large x-height (e.g. a slab/`Iosevka`-like) for projector legibility.
- **Slide 7 corner motif** — anchor: `storyboard.md § Слайд 7` (lines 219–220) — since this slide stays up for the entire Q&A, ensure the corner symbol does not encroach on the 4 contribution lines; a small footer-right placement is fine, but keep it monochrome so it does not compete with the read-aloud list.

---

## Recommended palette (conservative-academic, projector- and colorblind-safe)

Use **one accent + neutral greys + black on near-white**. Avoid red/green as the sole carrier.

- **Background:** `#FFFFFF` or a very slight warm white `#FCFCFA` (pure black-on-white maximizes projector contrast; avoid dark themes — they wash out and look non-academic).
- **Primary ink (text, diagram lines, "present" nodes):** near-black `#1A1A1A`.
- **Single accent (the ONE highlight color — callout arrows, "Наша система" column, anchor captions, the 2FA lock):** a deep **academic blue** `#1F3A5F` (or KNU-appropriate institutional blue). Blue is the safest single accent for deuteranopia/protanopia and holds contrast on cheap projectors.
- **Secondary / "gone" / negative state:** mid-grey `#7A7A7A` for dashed "removed" nodes and for the de-emphasized competitor cells.
- **✓ / ✗:** encode by **glyph shape first** (bold ✓ vs bold ✗), both in near-black. If you want reinforcement, ✓ = accent blue, ✗ = grey — do **not** use red/green.
- **Add vs remove arrows (slide 4):** solid accent-blue arrow + filled node = add; dashed grey arrow + hollow grey node = remove. Line style, not hue, is the signal.

This is a strict 3-ink scheme (black, one blue, one grey). It satisfies "one accent color + greys," survives grayscale, and reads on a weak projector.

## Recommended Beamer theme / template approach

- **Engine:** XeLaTeX (already chosen) — required for Cyrillic + a real serif/sans pairing. Use `fontspec`; pick a Ukrainian-complete face (e.g. a Cyrillic-covering serif for body, a clean sans for labels). Set `\setmainfont` and a high-x-height mono via `\setmonofont`.
- **Theme:** start from `\usetheme{default}` (NOT Madrid/Warsaw/etc. — those force footline/headline ornament and institutional color bars). Then strip everything:
  - `\setbeamertemplate{navigation symbols}{}` — kill nav arrows.
  - `\setbeamertemplate{footline}{}` and `\setbeamertemplate{headline}{}` — no bars (Winston: remove footer/header).
  - `\setbeamertemplate{frametitle}{}` or simply omit `\frametitle` on content slides — the rule is "remove the title from every content slide." Keep titles only in speaker notes.
  - `\setbeamercolor{background canvas}{bg=white}`; define one accent: `\definecolor{accent}{HTML}{1F3A5F}` and `\setbeamercolor{structure}{fg=accent}`.
  - `\setbeamertemplate{itemize items}{}` or a single small dash — no bullet ornaments.
  - No logo (`\logo{}` left unset; Winston: logos are distraction).
- **Aspect ratio:** confirm the projector. Older committee rooms are frequently **4:3**; if so, `\documentclass[aspectratio=43]{beamer}` and size all diagrams for 4:3 (this is also the binding constraint behind the slide 3 / 5 density blockers — 16:9 would give marginally more room but does not fix them).
- **Font floor:** set the base font so that body lands ≥40pt at projection. Practically, design at `\documentclass[14pt]{beamer}` base (or use the `beamer` `t` size options) and verify the *thumbnail test* from how-to-speak.md line 28 — if any slide looks heavy at thumbnail size, cut.
- **TikZ:** define named styles once in the preamble (`wgbus`, `wgpeer`, `wggone`, `callout`, `lock`) and reuse on slides 4/5/6/7 so the motif and callout-arrow style are byte-for-byte consistent.

---

## Verdict

Solid Winston-aligned structure and a genuinely good reusable symbol motif, but **NOT yet build-ready**: slide 5 (sequence) and slide 3 (matrix) are over-stuffed and will breach the 40pt floor / repeat the thesis p.25 overlap, and the red-green ✓/✗ + add/remove encoding must become shape-redundant before any TikZ is drawn.

