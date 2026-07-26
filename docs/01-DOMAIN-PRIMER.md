# Domain Primer: Cochlear Implants, Audiology, and Digital Audio

> Shared technical grounding for PRELUDE. Cochlear implant signal processing is
> counterintuitive, and plausible-sounding reasoning fails here in ways that are hard to
> detect by ear. Read this before writing or reviewing DSP code.

---

## 1. What a cochlear implant actually does

A cochlear implant (CI) does **not** amplify sound. It bypasses the entire mechanical and
sensory apparatus of the ear and stimulates the auditory nerve directly with electrical
pulses. Understanding the signal chain is essential, because a pre-processor can only intervene at
one specific point in it.

### 1.1 The signal chain

```
acoustic input ──► [ sound processor: external, worn behind ear ] ──► RF coil ──►
   ├─ microphone(s) or Bluetooth/telecoil stream
   ├─ pre-emphasis + front-end AGC / compression
   ├─ analysis filterbank        (12–22 bands)
   ├─ envelope extraction        (rectify + LPF, or Hilbert)
   ├─ channel selection          (n-of-m peak picking, strategy-dependent)
   ├─ loudness mapping           (acoustic dB ──► electrical current units, log compression)
   └─ pulse generation           (biphasic pulse train, interleaved across electrodes)
                                            │
                                            ▼
                     [ implanted receiver/stimulator + electrode array ]
                                            │
                                            ▼
                          spiral ganglion / auditory nerve fibers
```

**The critical architectural fact:** everything from the analysis filterbank
onward is fixed firmware inside the recipient's processor, tuned by an audiologist. We
cannot change it. We can only change the *acoustic signal presented to it*. This makes the task a **pre-compensation** (or pre-distortion) problem, exactly analogous to
pre-emphasis for a known lossy channel:

> Find a transform `g` such that `CI(g(x))` is perceptually closer to the listener's
> memory of `x` than `CI(x)` is.

Note that `g` is *not* trying to make `g(x)` sound good. `g(x)` will often sound strange
or unpleasant to a normal-hearing listener. It is optimized for what survives the CI.

### 1.2 Tonotopy and the place code

The cochlea is tonotopically organized: high frequencies at the base, low at the apex.
The **Greenwood function** maps characteristic frequency to distance along the cochlea:

```
F(x) = A · (10^(a·x) − k)        with human values A = 165.4, a = 2.1 (x normalized 0..1), k = 0.88
```

A typical electrode array is 16–31 mm long and, in practice, is inserted only 18–25 mm
into a ~35 mm cochlea. Consequences:

- **The apex is not reached.** The most apical electrode typically sits at a place whose
  natural characteristic frequency is 400–1000 Hz, yet the processor assigns it a band
  starting near 100–300 Hz. This creates a systematic **frequency-place mismatch** — the
  listener hears everything shifted upward in place, which is why CI sound is described
  as high-pitched, "chipmunk-like", or metallic on initial activation.
- The brain partially re-maps this over months to years, but never perfectly.
- **Design implication:** naive frequency shifting to "fix" the mismatch usually makes
  things worse in an acclimated user. Their cortex has already adapted to *their* map.
  Any frequency warping must be validated perceptually, not assumed.

### 1.3 The electrical dynamic range — the single most brutal constraint

| | Acoustic hearing | Electrical (CI) hearing |
|---|---|---|
| Dynamic range | ~120 dB | **~6–20 dB** (often quoted 6–15 dB) |
| Just-noticeable intensity steps | ~1 dB | ~0.5–1 dB, but only ~20 total steps |
| Frequency channels | ~3,500 inner hair cells, ~30 independent critical bands | 12–22 electrodes, **~4–8 functionally independent** |
| Temporal fine structure | Preserved (phase-locking to ~4–5 kHz) | **Essentially absent** |

Each electrode is characterized by two levels set in clinic:
- **THR / T-level**: threshold of electrical hearing.
- **MCL / C-level**: most comfortable (or maximum comfortable) loudness.

The processor compresses the ~40–60 dB input acoustic range into the T–C range using a
logarithmic-ish loudness growth function (often an "instantaneous nonlinear compression"
with an adjustable Q-factor / base). **Everything the listener hears lives inside that
tiny window.** This is why heavily compressed, loudness-managed source material tends to
survive CI transmission better than wide-dynamic-range material — and why the wide
dynamic range of a good classical recording is largely wasted or lost.

### 1.4 Envelope vs. temporal fine structure (TFS)

Decompose a bandpass signal `s(t)` via the Hilbert transform:

```
s(t) = E(t) · cos(φ(t))
       ▲          ▲
    envelope   fine structure (instantaneous phase/frequency)
```

**Standard CI strategies transmit only `E(t)`.** The fine structure is discarded and
replaced by a fixed-rate electrical pulse carrier. This is the root cause of nearly every
CI music deficit:

- **Pitch (F0)** is normally coded by TFS phase-locking plus resolved harmonics. With
  envelope-only coding, pitch must come from (a) coarse place cues and (b) the envelope
  periodicity rate, which supports pitch only up to ~300 Hz and weakly.
- **Timbre** depends on the relative amplitude of resolved harmonics. With 8–12 effective
  channels, harmonics below ~1.5 kHz are unresolved — several harmonics fall inside one
  analysis band and are merged into a single envelope value.
- **Melody** recognition without rhythm cues is typically near chance for many CI users.
- **Rhythm and tempo** are preserved *well* — envelope modulation is exactly what survives.
  This is a lever worth exploiting.

### 1.5 Channel interaction / current spread

Electrical current in the conductive perilymph spreads from the stimulating electrode,
decaying roughly exponentially with distance:

```
I(d) ≈ I₀ · e^(−d/λ)     λ typically corresponds to ~3–8 dB/mm falloff
```

Adjacent electrodes therefore excite overlapping neural populations. Effects:

- The effective number of independent channels saturates at **~4–8**, regardless of
  whether the array has 12 or 22 contacts. Adding electrodes past that point yields
  diminishing returns.
- **Spectral smearing**: sharp spectral peaks (formants, harmonics) are blurred.
- Mitigations in-device: interleaved (non-simultaneous) stimulation — the "S" in CIS —
  plus current focusing (tripolar/partial-tripolar, phased array).
- **Design implication:** deliberately *increasing spectral contrast*
  (sharpening peaks, deepening valleys) before transmission can partially pre-compensate
  for the smearing that follows. This is one of the most promising, evidence-supported
  levers available to us.

### 1.6 Coding strategies

| Strategy | Vendor | Mechanism | Notes |
|---|---|---|---|
| **CIS** (Continuous Interleaved Sampling) | generic / MED-EL | All *n* channels stimulated every cycle, interleaved | Simple, the standard research baseline. What CI_SIM models. |
| **ACE** (Advanced Combination Encoder) | Cochlear (Nucleus) | **n-of-m**: pick the *n* highest-envelope of *m* bands each frame (typ. 8–12 of 22) | Default for most Nucleus users. Peak-picking discards low-energy spectral detail. |
| **SPEAK** | Cochlear | n-of-m, lower rate, adaptive n | Older. |
| **FSP / FS4** | MED-EL | Attempts to deliver fine structure on apical channels via zero-crossing-triggered pulse bursts | Better F0/music outcomes reported. |
| **HiRes / Fidelity120 / Optima** | Advanced Bionics | High rate + **current steering** (weighting adjacent pairs to create virtual intermediate channels) | Claims more spectral resolution. |

**Stimulation rate** is typically 500–2,400 pulses/s per channel. Higher rate gives finer
envelope sampling but more channel interaction and higher power draw.

**n-of-m matters enormously for pre-processing.** If only the 8 loudest of 22 bands are transmitted per
frame, then any spectral content a pre-processor adds that fails to win a peak-picking contest is
*deleted entirely*. Adding energy is not neutral — it can evict other content. Conversely,
removing masking content can *promote* useful content into the transmitted set. This makes
n-of-m a competitive, zero-sum allocation problem, and it is a strong argument for source
separation and selective de-cluttering rather than additive enhancement.

---

## 2. Why music and recorded media are especially hard

CI processors are optimized for **real-time speech in moderate noise**. Recorded music
streamed over Bluetooth violates nearly every assumption:

1. **Polyphony.** Multiple simultaneous instruments compete for the same small number of
   channels. Speech is one source; a mix is many. n-of-m peak-picking under polyphony
   produces a rapidly fluctuating, incoherent channel selection.
2. **Wide bandwidth.** Music has meaningful content from 30 Hz to 16 kHz. The CI's
   analysis range is roughly 100/200 Hz to 8 kHz. Everything outside is gone.
3. **Wide dynamic range.** See §1.3. A 60 dB orchestral crescendo maps into a ~10 dB
   electrical window.
4. **Pitch and harmony are the content.** These are precisely the dimensions the envelope
   code destroys. Rhythm survives; melody and harmony do not.
5. **Front-end AGC fights the music.** The processor's automatic gain control and noise
   reduction were designed to suppress steady non-speech sounds. Sustained instrumental
   passages can be treated as noise and attenuated.
6. **Reverb.** Reverberant tails fill the envelope valleys between notes and syllables.
   Because the CI transmits only envelopes, reverb is disproportionately destructive — it
   directly smears the one cue that survives. Dereverberation is high-value.
7. **Codec interaction.** Bluetooth A2DP (SBC/AAC/aptX) is a lossy perceptual codec that
   discards content it judges masked *for a normal-hearing listener*. That masking model
   does not describe a CI listener. Content the codec discards as inaudible may have been
   exactly the content that would have survived; content it preserves may be irrelevant.
   Codec artifacts (pre-echo, band truncation) also land in the envelope.

**Bluetooth streaming does not bypass the processor's back-end.** It bypasses the
microphone and (usually) some front-end AGC, but the filterbank, envelope extraction,
channel selection, and loudness mapping all still apply. This is what makes pre-processing viable:
there is a stable, deterministic transform between the file we control and the percept.

---

## 3. Bimodal hearing

A **bimodal** listener uses a cochlear implant in one ear and an acoustic hearing aid in
the other. It is a common configuration, and one with particular relevance to music.

### 3.1 What the acoustic ear contributes

Residual low-frequency acoustic hearing is disproportionately valuable, because it supplies
precisely what the implant cannot:

- **Temporal fine structure** below ~1 kHz, giving genuine F0 and pitch perception.
- **Resolved low harmonics**, giving timbre, instrument identity, and voice quality.
- **A fundamental frequency to track**, which is why melody recognition in bimodal
  listeners is markedly better than with an implant alone.

The combination is genuinely synergistic — bimodal performance typically exceeds either
device alone, and the benefit for *music* is larger than the benefit for speech.

### 3.2 What makes bimodal hard

- **Loudness balance** between an acoustic and an electric percept must be matched, and
  drifts as the acoustic ear changes.
- **Frequency-place mismatch across ears**: the same acoustic frequency is delivered to
  different tonotopic places in each ear, impeding binaural fusion.
- **Timing mismatch**: hearing-aid processing delay (~5–10 ms) differs from implant
  processing delay, disrupting interaural time cues.
- **In progressive hearing loss the acoustic ear is a moving target.** Every audiogram
  shift changes the optimal division of labour between the two ears.

### 3.3 The design constraint this imposes

Where residual acoustic hearing is expected to decline, a system built around it must
**degrade gracefully to implant-only**. Concretely:

- Do not build anything that structurally *depends* on residual acoustic hearing.
- Prefer a **two-path architecture** — a processing path for the implanted ear and a
  separate one for the aided ear, with an explicit, adjustable crossover. The system can
  then be rebalanced as the audiogram changes and eventually collapse to implant-only by
  setting the acoustic path's contribution to zero. That makes the transition a
  configuration change rather than a rewrite.
- Treat any bimodal calibration opportunity as **time-limited** (see §4).

---

## 4. Bimodal listeners as translators between acoustic and electric hearing

Cochlear implant simulations are conventionally validated by playing vocoded audio to
**normal-hearing listeners**. This is a proxy measure, and a weak one: it establishes what
a vocoder sounds like to an intact ear, not what an implant sounds like to an implanted
one. The direct question is hard to ask, because someone who has only ever heard through an
implant has no acoustic reference for comparison, and someone with normal hearing has no
implant.

A bimodal listener who acquired hearing loss after developing normal hearing is an unusual
and valuable exception. Such a listener

1. has **intact acoustic memory** and vocabulary for natural timbre,
2. **currently hears through an implant** on one side, and
3. **retains acoustic hearing** on the other, permitting genuine within-subject comparison
   of the same stimulus through two different transduction paths.

This enables a calibration loop unavailable by any other route:

```
  source audio x
       │
       ├──────────────► aided ear (acoustic reference)  ─┐
       │                                                  ├──► listener reports the difference
       ├──────────────► implanted ear (electric percept) ─┘
       │
       └──► candidate simulation  Ŝ(x) ──► presented to the aided ear only
                                          │
                                          └──► "does this match what the implant sounds like?"
                                                        │
                                                        ▼
                                          iteratively fit simulator parameters
```

The second loop is the valuable one. Presenting a candidate simulation to the acoustic ear
and asking whether it matches the implanted ear's percept of the same source converts an
otherwise unfalsifiable model into a fitting problem with a real error signal.

**Where hearing loss is progressive, this window closes.** Calibration data can only be
collected while the listener can still make the comparison, whereas engineering work can be
done at any time. That asymmetry should drive scheduling: capture perceptual data early,
even before the software is good.

### 4.1 Elicitation caveats

Subjective auditory report is fragile. Protect the data:

- Use **forced-choice and matching tasks** rather than open-ended description wherever
  possible. "Which of these two is closer?" is testable; "describe what you hear" is useful
  for generating hypotheses but not for testing them.
- **Randomise and blind** presentation order, by script rather than by hand. Include catch
  trials (identical pairs) to estimate response noise; without a noise floor, a 60%
  preference is uninterpretable.
- Beware **acclimatisation and learning effects** across sessions.
- Beware **anchoring**: a listener who has heard a particular simulation many times may
  begin treating it, rather than the implant, as the reference.
- Keep sessions short. Auditory fatigue degrades discrimination, and fatigued data is
  indistinguishable from a null result.
- Log everything. An unlogged session is lost data, and where the reference ear is
  declining, the supply of sessions is finite.

---

## 5. Levers available to a pre-processor

Ranked roughly by expected value, with the mechanism each exploits:

| Lever | Mechanism | Expected value |
|---|---|---|
| **Dereverberation** | Reverb fills envelope valleys; envelopes are all the CI transmits | High, well-supported |
| **Source separation / reduce polyphony** | Fewer competing sources → cleaner n-of-m channel allocation | High; demonstrated in CI music literature (simplified/reduced-instrument arrangements are preferred by CI users) |
| **Spectral contrast enhancement** | Pre-sharpens peaks to counteract current-spread smearing | High; direct pre-compensation of a known distortion |
| **Dynamic range compression matched to electrical DR** | Fits source into the ~10 dB usable window deliberately, rather than letting the processor's generic AGC do it | High |
| **Bandwidth remapping / frequency compression** | Folds musically important content into the 200 Hz–8 kHz transmitted range | Medium; risks disrupting an acclimated map — must be validated perceptually |
| **Harmonic / F0 enhancement** | Strengthens the periodicity cues that weakly survive in the envelope | Medium |
| **Transient & onset sharpening** | Rhythm is the best-preserved dimension; strengthening it plays to the CI's strength | Medium, cheap to try |
| **Masker removal (de-cluttering)** | Under n-of-m, removing a loud irrelevant band *promotes* a quieter relevant one | Medium–high, underexplored |
| **Codec-aware preparation** | Avoid handing the Bluetooth codec decisions that assume normal-hearing masking | Low–medium; hard to control |

**Anti-lever (do not do):** naive loudness maximization / brickwall limiting. It destroys
the envelope modulation depth that is the CI's only real information channel.

---

## 6. Objective metrics, and why they are not enough

Available instrumental measures:

- **STOI / ESTOI** — short-time objective intelligibility; correlates with speech
  intelligibility, envelope-based, so reasonably relevant to CI.
- **NCM** (Normalized Covariance Metric) — envelope-correlation based; among the better
  predictors for vocoded/CI speech.
- **STMI** (Spectro-Temporal Modulation Index) — sensitive to the modulation content that
  CIs transmit.
- **PESQ / POLQA** — designed for telephony codecs; poor fit for CI, use with suspicion.
- **Modulation depth / envelope correlation per channel** — a direct, interpretable
  measure of what actually reaches the nerve. Recommended as the primary internal
  metric.
- For music: pitch salience, chroma/melodic contour agreement, spectral centroid and flux
  distance, onset-detection F1.

**None of these are validated against CI percepts, and optimizing them blindly is a known
failure mode.** They are useful as fast regression signals between listening sessions —
to catch outright breakage and to rank candidates before spending scarce listening time.
The human loop remains the ground truth. Every metric adopted should be recorded in
`05-EVALUATION-PROTOCOL.md` along with an honest statement of what it does *not* capture.

---

## 7. Digital audio facts that keep mattering here

- **Nyquist.** At a 16 kHz sample rate the maximum representable frequency is 8 kHz. Any
  filterbank band edge above that is invalid. This is not a hypothetical mistake — see
  `03-PRIOR-ART.md` for a filterbank that silently ran at half its nominal channel count
  for exactly this reason. A rate of 16 kHz is otherwise reasonable for CI simulation,
  since the device's own analysis tops out near 8 kHz, but band edges must then be defined
  relative to 8 kHz rather than to the sample rate. PRELUDE defaults to 20 kHz so that a
  300–8500 Hz analysis range is representable.
- **Envelope extraction** must be `rectify → lowpass` (typically 50–400 Hz cutoff) or
  `|hilbert(x)|`. Half-wave rectification *without* a lowpass does not produce an
  envelope — it produces a distorted copy of the original signal, full of new harmonics.
- **A vocoder needs a carrier.** The canonical noise-vocoder is
  `Σᵢ envelopeᵢ(t) · bandpassᵢ(noise)` — extract the envelope per band, then multiply it by
  a band-limited noise (or tone) carrier and sum. Summing rectified band signals is not a
  vocoder and does not simulate a CI.
- **Analytic signals / Hilbert** are the cleanest envelope route, and match what several
  established reference simulators use.
- **MP3/AAC are lossy** and already discard content per a normal-hearing masking model.
  Prefer lossless sources for research material where possible, so that one perceptual
  model is not stacked on top of another.
- **Loudness normalization** for listening tests must be explicit (target LUFS or matched
  RMS), otherwise level differences dominate every subjective comparison and invalidate it.

---

## 8. Glossary

| Term | Meaning |
|---|---|
| **ACE** | Advanced Combination Encoder; Cochlear Ltd's default n-of-m strategy |
| **AGC** | Automatic Gain Control |
| **C-level / MCL** | Most comfortable loudness level, per electrode |
| **CI** | Cochlear Implant |
| **CIS** | Continuous Interleaved Sampling coding strategy |
| **EAS** | Electric-Acoustic Stimulation (hybrid: implant + acoustic in the *same* ear) |
| **F0** | Fundamental frequency (perceived pitch of a periodic sound) |
| **Greenwood function** | Maps cochlear position to characteristic frequency |
| **MAP** | The individualized program in a CI processor (T/C levels, strategy, rate, allocation) |
| **n-of-m** | Transmit only the *n* highest-energy of *m* analysis bands per frame |
| **pps** | Pulses per second (stimulation rate) |
| **T-level / THR** | Threshold level, per electrode |
| **TFS** | Temporal Fine Structure |
| **Tonotopy** | Frequency-to-place organization of the cochlea |
| **Vocoder** | Analysis/resynthesis by band envelopes; the standard CI simulation method |

---

## 9. References and further reading

Foundational and directly relevant. Entries marked (*) drive design decisions in this
codebase and are worth reading before modifying the corresponding stage.

- **Shannon, R. V., Zeng, F.-G., Kamath, V., Wygonski, J., & Ekelid, M. (1995).**
  *Speech recognition with primarily temporal cues.* Science, 270(5234), 303–304. (*)
  The founding noise-vocoder paper. Establishes how few channels speech intelligibility
  requires — and by contrast how many music does.
- **Loizou, P. C. (1998).** *Mimicking the human ear: an overview of signal-processing
  techniques for converting sound to electrical signals in cochlear implants.* IEEE Signal
  Processing Magazine, 15(5), 101–130. (*) The standard tutorial on coding strategies.
- **Greenwood, D. D. (1990).** *A cochlear frequency-position function for several
  species — 29 years later.* JASA, 87(6), 2592–2605. (*) The frequency-to-place map used
  by the ``greenwood`` filterbank spacing.
- **Glasberg, B. R., & Moore, B. C. J. (1990).** *Derivation of auditory filter shapes from
  notched-noise data.* Hearing Research, 47(1–2), 103–138. (*) ERB scale, used by the
  ``erb`` spacing.
- **Slaney, M. (1993).** *An efficient implementation of the Patterson–Holdsworth auditory
  filter bank.* Apple Computer Technical Report #35.
- **McDermott, H. J. (2004).** *Music perception with cochlear implants: a review.* Trends
  in Amplification, 8(2), 49–82. Establishes the rhythm-preserved / pitch-degraded
  asymmetry that motivates most of §5.
- **Limb, C. J., & Roy, A. T. (2014).** *Technological, biological, and acoustical
  constraints to music perception in cochlear implant users.* Hearing Research, 308, 13–26.
- **Bierer, J. A. (2010).** *Probing the electrode–neuron interface with focused cochlear
  implant stimulation.* Trends in Amplification, 14(2), 84–95. Background for the channel
  interaction model.
- **ITU-R BS.1770-4 (2015).** *Algorithms to measure audio programme loudness and true-peak
  audio level.* (*) Implemented in ``prelude.audio.loudness``.
- **Bimodal benefit literature** — relevant to the two-path crossover design in §3.3;
  see reviews of combined electric and acoustic stimulation outcomes.

Corrections and additions to this list are welcome; see `CONTRIBUTING.md`.
