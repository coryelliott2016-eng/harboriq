# HarborIQ — U.S. Copyright Registration Guide

This is a ready-to-file packet for registering HarborIQ's source code with
the U.S. Copyright Office. **You (Cory Elliott) must personally create the
eCO account, sign, and submit** — copyright applications are filed under
penalty of a false-statement provision (17 U.S.C. § 506(e)) and require
your own identity and payment, so this cannot be filed on your behalf.
Everything below is prepared so filing takes about 15–20 minutes.

This is *not* legal advice. Given the stakes (this is the asset you intend
to sell/license and fold into your asset-protection structure), a 20–30
minute consult with an IP attorney before you click "Submit" is a
reasonable, low-cost step — especially to sanity-check the AI-authorship
disclosure language below, which is a genuinely unsettled area (see
"Legal background" at the end).

## Facts as of this filing (verify against copyright.gov before submitting — these change)

| Item | Current value | Source |
|---|---|---|
| Fee, Standard Application, electronic | $65 (a $65→$85 increase was proposed March 20, 2026 and may have taken effect by the time you file — check [copyright.gov/about/fees.html](https://www.copyright.gov/about/fees.html)) | [Federal Register NPRM, Mar. 20, 2026](https://www.federalregister.gov/documents/full_text/xml/2026/03/20/2026-05529.xml) |
| Processing time | ~3–4 months standard; $800 add-on for 5-business-day "Special Handling" | [copyright.gov fees/eCO guidance](https://www.copyright.gov/about/fees.html) |
| Filing system | Electronic Copyright Office (eCO) at [copyright.gov/eco](https://www.copyright.gov/eco/) | U.S. Copyright Office |
| AI-authorship disclosure requirement | In force since March 2023 guidance; unchanged after *Thaler v. Perlmutter* cert denial (Mar. 2, 2026) — that case only confirmed AI *cannot itself* be listed as author, it did not add new rules for AI-*assisted* works like this one | [copyright.gov/ai/ai_policy_guidance.pdf](https://www.copyright.gov/ai/ai_policy_guidance.pdf); [Mayer Brown, Mar. 11, 2026](https://www.mayerbrown.com/en/insights/publications/2026/03/supreme-court-denies-review-in-ai-authorship-case) |

## Step-by-step

1. Go to [copyright.gov](https://www.copyright.gov) → **Register a Copyright** → log in / create an eCO account.
2. **"Register a New Claim" → "Start Registration."**
3. **Type of Work:** select **Literary Work** (source code for a computer program is registered under this category per [Circular 61](https://www.copyright.gov/circs/circ61.pdf), not "Software"/"Computer File" — there is no separate software category).
4. **Application type:** use the **Standard Application** — do not use "Single Application"; only the Standard Application has the fields needed to disclaim AI-generated material.
5. **Title of Work:** `HarborIQ` (or `HarborIQ Source Code (v1.0)` if you want to tie it to a specific commit/release — recommended, since you'll likely file supplementary registrations as the code evolves materially).
6. **Year of Completion:** `2026`.
7. **Publication status:** Likely **Unpublished** — you have not distributed copies of the software to the public; operating it as a private/internal SaaS you control is generally not "publication" in the copyright sense (no copies are being distributed). If you've already sold/delivered the software or source to a third party, mark **Published** instead and give the date/nation of first publication (United States).
8. **Author:**
   - Name: **Cory Elliott**
   - Author created: *(see exact wording below — do not leave this generic)*
   - Citizenship/domicile: United States
   - Work made for hire: **No** (you're filing as the individual human author, not an employer)
9. **Claimant:** Cory Elliott, same address as the author.
10. **Limitation of Claim → "Material Excluded" → "Other":** *(see exact wording below)*
11. **Rights and permissions / correspondent:** your contact info.
12. **Certification:** you personally certify — read it, it's a legal statement.
13. **Deposit copy upload:** upload `docs/copyright_deposit_first10_last10.pdf` (already generated in this repo — see "Deposit copy" section below for what it is and why it's safe to submit).
14. **Pay the fee**, submit, save your confirmation/case number.

## Exact field language to use

**"Author Created" field** (describes your human contribution — be specific, this is the field the Office actually weighs):

> Computer program source code. The author independently conceived the
> software's overall system architecture, database schema, business logic,
> security model, and user-facing feature design, and directed, reviewed,
> tested, corrected, and integrated all source code — including portions
> produced with the assistance of AI-based code-generation tools acting
> under the author's detailed specifications and iterative review — into
> the finished, functioning program.

**"Material Excluded" / "Other" field** (required disclosure — more than
de minimis AI-generated content must be excluded from the claim):

> This work was created in part with the assistance of AI-based software
> development tools. To the extent portions of the source code text were
> generated by artificial intelligence rather than directly typed by the
> human author, such AI-generated code text is excluded from this claim.
> The author claims only the human-authored architecture, design,
> selection, arrangement, and combination of the software's components,
> and any code the author personally wrote, edited to a creative degree,
> or substantially modified.

**If you'd rather not draft your own excluded-material description**, the
Office's guidance explicitly allows a general statement instead — it will
then follow up with you directly:

> The work contains material generated by artificial intelligence.

Either approach is consistent with current guidance
([copyright.gov/ai/ai_policy_guidance.pdf](https://www.copyright.gov/ai/ai_policy_guidance.pdf)).
The general statement is lower-effort and defers the hard line-drawing to
the examiner; the detailed version above is more precise but is *your*
representation, so only use it if you're comfortable standing behind it.

## Deposit copy — what's in it and why

U.S. law requires depositing a copy of the work, but computer programs
containing trade secrets or confidential/competitive material don't have
to deposit the whole program. This repo includes a script
(`scripts/generate_copyright_deposit.py`) that builds the deposit using
the **"first 10 and last 10 pages of source code"** option — the simplest
of three trade-secret deposit methods recognized in
[37 C.F.R. § 202.20(c)(2)(vii)(A)](https://www.copyright.gov/eco/help-deposit.html)
— rather than the full first-25/last-25 pages a non-confidential program
would submit. "Page" = 40 lines of code per the Office's own rule of
thumb, so this deposits 400 lines from the start and 400 from the end of
a single combined listing of the backend (Python) and frontend
(TypeScript/React) source, in deterministic file order, excluding tests
and autogenerated migration boilerplate.

This matters for you specifically because copyright deposits become
*publicly inspectable* once registered (17 U.S.C. § 705(b)) — an
unredacted full-source deposit can be used against you later to argue you
waived trade-secret protection over your dispatch-scoring algorithm,
security code, etc. (this actually happened in a real case:
[GEICO v. Capricorn, discussed here](https://www.crowelltradesecretstrends.com/2020/03/geico-earns-victory-at-intersection-between-copyright-and-trade-secret-law-covering-source-code/)).
The 10/10-page option avoids that by depositing far less material while
still satisfying the legal deposit requirement.

The generated files are:
- `docs/copyright_deposit_first10_last10.txt` — plain text (kept in the
  repo for review/regeneration).
- `docs/copyright_deposit_first10_last10.pdf` — **upload this one** to
  eCO; the Office prefers PDF.

Regenerate anytime the codebase changes materially (e.g., before a future
supplementary registration) with:
```
python scripts/generate_copyright_deposit.py
python scripts/txt_to_pdf.py docs/copyright_deposit_first10_last10.txt docs/copyright_deposit_first10_last10.pdf
```

## Legal background (why this is genuinely a gray area right now)

- Copyright protects only human-authored creative expression. Purely
  AI-generated output — with no meaningful human creative control over
  the expression itself — is not registrable
  ([copyright.gov AI guidance](https://www.copyright.gov/ai/ai_policy_guidance.pdf)).
- *Thaler v. Perlmutter* — cert denied March 2, 2026 — confirmed only the
  narrow point that an AI system itself cannot be listed as an author;
  it did not resolve (and the courts have explicitly said they haven't
  resolved) the much more common, harder case of a human directing and
  editing AI-assisted output, which is HarborIQ's actual situation
  ([Mayer Brown](https://www.mayerbrown.com/en/insights/publications/2026/03/supreme-court-denies-review-in-ai-authorship-case);
  [CASRAI summary](https://casrai.org/news/thaler-v-perlmutter-scotus-cert-denial-human-authorship)).
- Where a human selects, arranges, or substantially modifies AI-generated
  material creatively enough that the result is an original work, the
  human-authored aspects *are* protectable — but the underlying
  AI-generated material itself is not, and must be excluded from the
  claim if it's more than de minimis. This is a case-by-case
  determination the Office makes on examination, not a bright-line rule
  you can fully resolve yourself before filing — hence the option above
  to file a general disclosure and let the examiner engage with you.
- If you omit the AI disclosure and it's later discovered, you risk the
  registration being unenforceable in litigation (17 U.S.C. § 411(b)) or
  administratively cancelled — so under-disclosing is the wrong direction
  to err in, even though it feels like it weakens your claim.

## After registration

- Save your certificate and case number somewhere durable (not just this
  repo — e.g., your document management/trust records, given your
  broader asset-protection setup).
- File a **supplementary registration** ("New Material Added/Other"
  field) after major future rewrites/versions rather than treating this
  one filing as covering all future code forever — each substantial new
  version is technically a new derivative work.
- Registration is a prerequisite to suing for infringement and to seeking
  statutory damages/attorney's fees, so keep this current if HarborIQ
  becomes commercially valuable enough to be worth defending.
