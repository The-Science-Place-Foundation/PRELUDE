# Contributing to PRELUDE

PRELUDE is a project of [The Science Place Foundation](https://scienceplacefoundation.org),
a 501(c)(3) nonprofit, released as open source for the audiology and hearing-research
community.

Contributions are welcome — code, documentation, domain corrections, and experimental
results alike.

**Domain expertise is as valuable as code here.** If you are an audiologist, a cochlear
implant user, or a hearing researcher and something in the documentation is wrong,
oversimplified, or out of date, please say so. That is one of the most useful contributions
this project can receive. You do not need to supply a patch, and you do not need to be a
programmer.

---

## Before writing DSP code

Read [`docs/01-DOMAIN-PRIMER.md`](docs/01-DOMAIN-PRIMER.md). Cochlear implant signal
processing is counterintuitive, and this is not a formality — the primer exists because a
predecessor project got several fundamentals wrong in ways that were undetectable by ear and
went unnoticed for months. [`docs/03-PRIOR-ART.md`](docs/03-PRIOR-ART.md) documents those
specific mistakes.

Three that trip people up repeatedly:

- **Rectification is not envelope extraction.** An envelope needs `rectify → lowpass` or
  `|hilbert(x)|`. Rectification alone yields a distorted copy of the band signal.
- **A vocoder needs a carrier.** `Σᵢ envelopeᵢ(t) · carrierᵢ(t)`. Summing filtered bands
  does not model an implant, because it preserves exactly the fine structure the device
  destroys.
- **Under n-of-m, adding energy can delete information.** Only the *n* loudest of *m* bands
  transmit; new content can evict existing content. Enhancement is competitive, not
  additive.

## Safety requirements

Any code path that can produce audio a human will hear **must** route through
`prelude.audio.loudness.prepare_for_playback`. Pull requests adding a bypass will not be
merged.

This is not defensive over-engineering. Listening-study participants often have residual
hearing that is irreplaceable and, in progressive conditions, already declining. An
over-level playback is not a recoverable mistake.

## Privacy requirements

**Never commit participant data.** Device programs (MAPs), audiograms, T/C levels,
electrode impedances, and raw listening-session records are health information. `.gitignore`
covers the standard locations; keep anything else in `private/`.

**Never commit audio containing a human voice**, however brief. A public repository is not
an appropriate place for a participant's recorded voice. Test fixtures are gitignored for
this reason — see [`tests/fixtures/README.md`](tests/fixtures/README.md).

**Use de-identified participant codes** (`P01`, `P02`) in all committed material, including
lab notebook entries. Never names.

**Write about roles, not people.** Use "the listener" or "the participant", and
they/them where a pronoun is unavoidable. A gendered pronoun narrows a
de-identified participant toward an individual and adds nothing.

### Enable the pre-commit hook

```bash
git config core.hooksPath .githooks
cp .githooks/identifiers.txt.example .githooks/identifiers.txt
# add any real names to identifiers.txt — it is gitignored
```

It **blocks** staged audio files, anything under `private/`, device profiles, and
content matching a participant identifier. It **warns** on clinical values and
gendered pronouns, which have legitimate uses in domain documentation.

This exists because the rules above were already correct and were still broken in
practice: a participant's first name reached six pushed commits before anyone
noticed, and removing it required rewriting public history. A check that runs
beats a rule that has to be remembered.

## Development

```bash
git clone <your fork>
cd prelude
pip install -e ".[dev,viz]"
pytest
ruff check prelude tests
```

### Testing expectations

New DSP code needs tests that check **behaviour**, not just shapes and absence of crashes.
A test asserting that output has the right dimensions catches very little; a test asserting
that fewer channels produce lower envelope fidelity catches real regressions.

Where a test encodes a specific historical mistake, say so in the docstring. Those tests are
documentation as much as verification, and a future contributor needs to know why an
apparently arbitrary assertion exists before deciding to relax it.

### Style

- `ruff` for linting and import order; 100-character lines.
- Type hints on public functions.
- Docstrings explain **why**, not what. The code shows what it does; the docstring should
  explain the constraint, the units, or the physiological reason for a choice.
- Comments justify non-obvious decisions. Do not narrate the next line.

### Configuration, not constants

Simulator and processing parameters belong in YAML, not in module-level constants. Any
parameter a researcher might reasonably want to sweep must be reachable from a config file
and must appear in `SimulatorConfig.hash()`, so that results remain attributable.

## Review before changing

Two review agents live in `.claude/agents/`. Both are steps, not suggestions.

**`prelude-code-review`** — before applying any change, and especially a change
made in response to a suspected bug. Its first job is not to review the fix but
to check whether the bug is real. The costly failures on this project have all
been correct-looking fixes to misdiagnosed problems.

**`audiology-review`** — before acting on any interpretation of listener data,
and before changing anything a listener will experience. Its job is to argue
against the interpretation, not confirm it.

### Verify the diagnosis before writing the fix

When something looks wrong, establish these before changing code:

- **What does the number actually measure?** Read the code that *produces* it,
  not only the code that consumes it. A field's meaning can change while its name
  does not.
- **Can the instrument resolve what it is being asked about?** A measure that
  smooths away the thing being varied reports "no difference" indistinguishably
  from "identical".
- **What else would produce this observation?** If the fix does not distinguish
  between the candidates, it is a guess.

### Simulate anything a listener will experience

Adaptive procedures, staircases, termination rules — run them against a synthetic
responder and check trial count and accuracy before deployment. Two calibration
procedures shipped here broken in ways a few minutes of simulation would have
caught, and were fixed only after the listener had run them twice.

## Pull requests

- One logical change per PR.
- Update relevant documentation in the same PR. This project has survived long dormant
  periods; stale documentation is worse than none, because it gets trusted.
- For a significant design decision, add an ADR under `docs/decisions/` following the
  existing format. Record the alternatives you rejected and why — that is usually the most
  useful part to a future reader.
- State clearly what you verified and what you did not.

## Reporting results

If you use PRELUDE in a study, negative results are welcome and worth reporting. An honestly
recorded null result is a contribution; an overstated one misleads people making decisions
about their own hearing.

## Scope

**In scope:** simulation fidelity, pre-processing methods, objective metrics, listening-study
tooling, device profile support, documentation, and reproducibility.

**Out of scope:** anything that programs, configures, or communicates with real implant
hardware. PRELUDE is research software and is not certified for clinical use. Device fitting
is the exclusive province of qualified audiologists, and this project will not blur that
line.

## Code of conduct

Be respectful and assume good faith. This project concerns disability and assistive
technology; contributors and users may be discussing their own hearing or that of people
close to them. Treat that with the seriousness it deserves.

## Licence

Contributions are accepted under the
[GNU Affero General Public License v3.0](LICENSE).

By submitting a pull request you agree that your contribution is licensed under
the AGPL-3.0, and that you have the right to license it — check with your
employer or institution if you are contributing in a work capacity, as many have
policies covering copyleft contributions.

The AGPL is a deliberate choice. It keeps the toolkit usable by anyone, including
commercially and in for-profit clinical settings, while ensuring that
improvements come back to the community rather than disappearing into a
proprietary product. If you build something on PRELUDE and distribute it — or run
it as a hosted service — your changes must be open too.
