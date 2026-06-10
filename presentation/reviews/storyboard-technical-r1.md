# Storyboard Technical Review — R1 (technical-accuracy lens)

Artifact: presentation/storyboard.md
Canon: presentation/research/thesis-facts.md (cross-checked vs chapter1/2/3.tex, conclusions.tex)
Reviewer mode: one-shot, read-only. Lens: catch anything WRONG / overstated / indefensible before slides.

---

## BLOCKER (must fix before building slides)

### B1 — Slide 3 matrix label "власний механізм TOTP" makes the DefGuard row internally inconsistent with thesis-facts §7
Storyboard sl.3 lists row "Власний механізм TOTP" and fills "DefGuard: ✓ TOTP". The
canonical §7 table (chapter1.tex r.431) puts DefGuard's 2FA mechanism as
"PSK-токен + TOTP/FIDO". That is fine. BUT the storyboard's stated 4 requirement-rows are:
«Стандартний WG-клієнт», «Незалежність від зовнішнього IdP», «Власний механізм TOTP»,
«Управління ключами». In thesis-facts §7 the four canonical requirements are: (1) стандартний
WG-клієнт, (2) незалежність від IdP, (3) власний TOTP, (4) управління ключами — and the
distinguishing fact is that DefGuard satisfies 2/3/4 and fails only #1, while WAG satisfies
1/2/3 and fails only #4. The storyboard's DefGuard column ✗✓✓✓ and WAG column ✓✓✓✗ are
CORRECT and consistent. No cell is wrong.
=> Downgrade: this is actually consistent. See N1 for the real (smaller) issue. NOT a blocker.
**Action: none for cell values.** (Kept here only to document that I verified every cell.)

### B2 — "917 = 917" / "0 %" presented as exact equality is defensible but the symbol "=" invites a measurement-error question
Canon (§8 / chapter3.tex r.1048-1049): WG plain tcp_p = 917 ± 35 Мбіт/с; this system = 917 ± 3,1
Мбіт/с. Medians are identical (917), so "917 = 917, 0 %" is literally TRUE per the table.
HOWEVER a professor can note the plain-WG figure has ±35 СКВ (3.8 % spread) — i.e. the "0 %"
is within noise, not a precise null. This is not wrong, but the deck currently has no defense
ready. **Fix:** in slide-6 speaker note add one sentence: «tcp_p — однакова медіана 917; розкид
±35 у plain-WG, тобто різниця в межах шуму вимірювання». Keep "0 %" on the slide but be ready to
say "в межах похибки". This is the single most likely number to be probed. **Treat as SHOULD-FIX
at minimum; promote to BLOCKER only because the slide currently asserts hard equality with zero
hedge in the notes.**

---

## SHOULD-FIX

### S1 — Slide 6 onboarding "×17" + the 1571/92 vs +1479 discrepancy: architect's handling is CORRECT, but tighten the note
- 1571 vs 92 ms: matches chapter3.tex r.1153-1154 and §8 exactly. ✓
- "×17": 1571/92 = 17.08 → "у 17 разів" matches chapter3.tex r.1158 verbatim. ✓
- conclusions.tex r.22-23 says "1571 мс проти 92 мс" (NOT "+1479"); chapter3.tex r.1324 says the
  2FA ceremony adds "+1479 мс". Both are in the thesis and both are internally consistent:
  1571 − 92 = 1479. So "1571 vs 92" (absolute) and "+1479" (delta) are the SAME fact stated two
  ways. The storyboard (sl.6 line 212-213) frames this as a "розбіжність"/discrepancy to flag —
  that framing is slightly misleading: it is NOT a contradiction, it is delta-vs-absolute.
  **Fix:** reword the speaker note from «розбіжність … прапорцюємо» to «1571 vs 92 = різниця
  1479 мс; на слайді показуємо абсолютні 1571/92, у тексті висновків — дельта +1479; це одне й те
  саме число». This removes a self-inflicted wound: as written, the presenter might accidentally
  tell the committee "there's a discrepancy in my thesis," which is the opposite of what's true.
  This is the most important narrative fix in the deck.

### S2 — Slide 2 "формально верифікований" (≈4000 LOC) — defensible but knowingly imprecise
Canon §2 r.48 says WireGuard ≈4000 LOC and "формально верифікований". The formal-verification
claim refers to the Noise/protocol proofs (the academic work), NOT the kernel module being
formally verified line-by-line. A networking professor may push: "що саме верифіковано — протокол
чи реалізація?" **Fix:** speaker note for sl.2 should pre-load: «формально верифікований — мається
на увазі протокол Noise / криптографічна модель (Donenfeld, symbolic/computational proofs), не вся
реалізація ядра». Keep it off the slide; have the answer ready.

### S3 — Slide 4 / Winston Star: "тунель фізично неможливий без запису вузла на сервері" — strong but technically defensible; one caveat
Canon §4 r.91-94 supports "session-gated … фізично неможливе без чинної автентифікованої сесії".
This is true for INBOUND peer acceptance: WireGuard's `wg set ... peer` is required server-side or
the handshake is dropped. Defensible. Caveat a sharp examiner may raise: a previously-added peer
remains valid until removed (the cleanup runs every 60 s, §6 r.192). So "фізично неможливо" is true
for *establishing* a new session, but *revocation* has up to a 60 s window. **Fix:** sl.4/sl.5
speaker note: add «відкликання — синхронне через API миттєво; фонове очищення прострочених — до 60 с».
Don't say "instant revocation" anywhere. The storyboard does not currently claim instant revocation,
so this is preventive, not a correction.

### S4 — Slide 7 bullet 2: "149 автотестів проходять, 7 функціональних сценаріїв … успішно"
Matches §9 (149 automated across 8 categories; 7 functional, all "Успішно"). ✓ Numbers fine.
Minor: bullet says "сервер (FastAPI + SQLite + керування wg0) і CLI-клієнт" — accurate per §4.
No fix needed; flagged only to confirm the two headline counts are canon-exact.

### S5 — Slide 6 CPU framing 34,8 % vs 20,6 %
Canon §8 r.291-292: 34,80 ± 0,72 (this system) vs 20,56 ± 0,36 (WG plain). Storyboard rounds to
"34,8 % vs 20,6 %" — correct rounding (20.56 → 20.6). ✓ The "від Docker namespace, не від
шифрування" attribution matches §8 r.296-298 verbatim. Good and defensible. **One add to note:**
%soft (mpstat) is the metric here and §8 r.299 warns %soft and %cpu (OpenVPN's pidstat) are NOT
directly comparable — so if the presenter is tempted to also say "and we beat OpenVPN on CPU",
that comparison must use the normalized per-Mbit column only. Add a one-line guard to the note so
the presenter doesn't volunteer a non-comparable CPU claim under questioning.

---

## NIT

### N1 — Slide 3 row name drift: storyboard says «Незалежність від зовнішнього IdP» (✓ = good); canon table row is «Залежність від IdP» (Так/Ні)
Same fact, inverted polarity. As long as the slide uses ✓ = "independent / no IdP dependency"
consistently, it is correct. Just make sure the ✓/✗ polarity on the slide is unambiguous (a ✓ in
the "IdP independence" row must mean Firezone/NetBird/Tailscale get ✗). The storyboard text (sl.3
r.129) already says these three get ✗ — consistent. Just label the row clearly on the slide as
«Без зовнішнього IdP» so ✓ intuitively = good.

### N2 — Slide 5 step 3 "TOTP ±30 с"
Canon §5 r.158-160: window is ±1 time-step = ±30 s, X=30 s. "±30 с" is correct shorthand. ✓
Be ready to say "±1 крок (RFC 6238 valid_window=1)" if asked.

### N3 — Slide 5 "JWT = HS256" / "secret ≥256 bit"
Canon §5 r.169 + chapter2.tex r.664-669: both tokens HS256, same secret, key ≥256 bit. ✓
Fernet/HKDF placement is correctly described as "у спокої, не у flow логіну" (sl.5 r.186 matches
§5 r.170-172 and chapter2.tex r.646-648). Good — this is exactly the kind of thing a crypto-minded
examiner probes, and the note pre-loads it correctly.

### N4 — Slide 5 omits the registration block by design
§5/§10 confirm registration exists and that unverified → 403. Storyboard explicitly says
"реєстрацію згадати вербально" (sl.5 r.170) and the note covers "без підтвердження → 403"
(r.185). Acceptable simplification for 5 min; not misleading by omission because the 403/enrollment
is in the note. ✓

### N5 — Slide 6 latency "24,20 = 24,20 мс" (p95, at rest)
Canon §8 r.264-265: WG plain p95 24,20; this system p95 24,20. Exact match. ✓ Note: under LOAD the
numbers differ (26,60 vs 27,26, bufferbloat +2,40 vs +3,06, §8 r.272-273). The slide only claims
the AT-REST parity, which is true. If asked about loaded latency, presenter should concede +0,66 ms
bufferbloat delta and attribute to the same Docker netfilter path, not encryption. Add to note.

### N6 — "×16,3 / ×12,3 / ×16 OpenVPN throughput" (open question 3, sl.6 third column)
If the architect adds the OpenVPN contrast column: tcp_t 16,3× (890/54,5 = 16,33 ✓, chapter3.tex
r.1032), tcp_p 12,3× (917/74,3 = 12,34 ✓, §8 r.284). Both canon-exact. The "×16" in open-question-3
is a loose restatement of 16,3× — if it goes on a slide, use 16,3× not 16×. CPU/Mbit 10,4× also
canon (§8 r.295). All safe IF added; recommend NOT adding to keep the WG-parity focus (the whole
narrative is "we ARE WireGuard", not "we beat OpenVPN").

### N7 — Slide 4 IP literals "10.10.0.1" server, "10.10.0.x" session peer
Canon §6 r.187-190: subnet 10.10.0.0/24, .1 = server, .2–.254 client pool. ✓ The `/32` allowed-ips
in `wg set wg0 peer <pubkey> allowed-ips <ip>/32` matches §6 r.178 exactly. ✓

---

## Cross-check summary (every number on the deck)
- 890 → 881 Мбіт/с, "1,0 %" tcp_t: ✓ (§8 r.280-281, chapter3.tex r.1048-1049)
- 917 = 917, "0 %" tcp_p: ✓ medians equal; hedge needed (B2)
- 24,20 = 24,20 мс p95 at rest: ✓ (§8 r.264-265)
- 1571 vs 92 ms, ×17: ✓ (chapter3.tex r.1153-1158); +1479 = same delta (S1)
- 34,8 % vs 20,6 % CPU: ✓ rounding correct (§8 r.291-292)
- ×16,3 / ×12,3 / ×10,4 (OpenVPN, if used): ✓ (§8 r.284, r.295)
- 5 хв intermediate JWT / 24 год full JWT: ✓ (§5, chapter2.tex r.203-211)
- ±30 с TOTP: ✓; 149 tests / 7 functional: ✓; 253 IP pool not on deck.
No fabricated or mismatched number found on any slide.

## Novelty-claim audit (the thing professors attack)
- "без зміни протоколу, без PSK": ✓ verbatim-faithful to abstract (§3 r.65-68) and conclusions.
- "сесія як вузол / session-gated": ✓ faithful to §4; defensible.
- NO illegal absolutes on the SLIDES ("перший/єдиний/унеможливлює"): the deck avoids "перший".
  It DOES use «єдиний повний рядок ✓» / «єдина, що ставить так у всіх чотирьох» (sl.3 r.126,130).
  This is defensible because it is scoped to THE FOUR STATED CRITERIA within the chosen comparison
  set (open-source/self-hosted/active-2025/explicit-WG), exactly as §7 r.223-233 frames it. KEEP the
  scoping verbal: presenter must say "серед розглянутих self-hosted рішень … за цими чотирма
  критеріями" — an unscoped "ми єдині" is puncturable. Add that scoping to the sl.3 note explicitly.
- §3 r.80-82 "у літературі відсутні рецензовані публікації щодо систематичного 2FA+WireGuard" — the
  storyboard sl.3 note repeats this. Defensible as stated ("систематичного підходу … немає, лише
  практичні реалізації"). Do NOT escalate to "ніхто ніколи не робив 2FA з WireGuard" — WAG/DefGuard
  obviously do 2FA. The note already says "лише практичні реалізації" — keep that exact hedge.

---

## VERDICT
**Technically SAFE to build, conditional on S1 (reframe 1571/92 vs +1479 as delta-not-discrepancy)
and B2 (add the "917 within ±35 noise" hedge to the slide-6 note); plus S2/S3/S5 speaker-note
guards.** No number is wrong, no cell in the matrix is wrong, the novelty claim is faithfully scoped
(no illegal "перший/єдиний" on slides). The only real risk is self-inflicted: the storyboard
currently calls the +1479/1571 relationship a "розбіжність," which it is not — fix that wording so
the presenter does not advertise a contradiction that doesn't exist.
