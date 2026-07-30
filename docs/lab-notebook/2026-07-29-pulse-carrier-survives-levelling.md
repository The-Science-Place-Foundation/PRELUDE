# Listening session — 2026-07-29 — the pulse-carrier preference survives level correction

**Type:** A — simulator fitting
**Session:** `6a8a34bc55c2`, pool `12439fbd2a04`
**Duration:** 6 minutes (02:35–02:41 UTC). Ended early, as the interface encourages.
**Responses:** 9 — 3 level-control, 1 catch, 6 scored judgements. None discarded.

This is the first session run against a level-matched pool and the first with a
level control. It produces the project's first finding that survives its own
controls, and it also exposed a new confound in the presentation order.

---

## The result

**`carrier_pulse` was chosen in 5 of the 5 trials it was presented in.**
Combined with the earlier session, resolved by stimulus name rather than index:

| candidate | chosen | presented | win rate |
|---|---|---|---|
| **`carrier_pulse`** | **11** | **11** | **100%** |
| `carrier_pulse_loose` | 0 | 2 | 0% |
| `maxima6` | 1 | 2 | 50% |
| `maxima12`, `ch08`, `ch16`, `maxima4`, `env900`, `ch06`, `rate500`, `rate1800`, `spread16` | 0 | 1–2 each | 0% |

Two things worth separating. `carrier="pulse"` resynthesises with discrete
pulse trains rather than noise bands, which is the physically faithful model of
electrical stimulation. And `carrier_pulse_loose` — the same carrier with
`synchronization=0.5` instead of 1.0 — lost both times it appeared. So the
preference is for **tightly synchronised pulsatile stimulation**, not merely for
"pulse".

## The level confound is excluded

This was the whole purpose of the rebuild. In the pool she heard:

- spread across all 20 candidates: **0.234 dB**
- `carrier_pulse`: **−26.61 LUFS**, mid-pack, 0.10 dB from the median
  (previously −27.94 against a field spanning 0.20 dB — 3.09 dB quieter)
- **level control: 2 of 3** chose the quieter interval. Mixed, so no evidence
  that level alone drives her choices. n = 3, so this is weak on its own; its
  value is that it is no longer *consistent* with a pure level effect.

## A new confound, and why it does not sink the result

`carrier_pulse` occupied **the second interval on all 5 trials** it appeared in,
and she chose the second interval on 5 of 6 real trials. Within this session
alone, "preferred that candidate" and "pressed the second button" predict
identical data.

Cause: the per-trial presentation order came up `[1,0]` six times running, and
because the information-gain selector names the leading candidate first in most
pairs, the leader landed in slot 1 every time. The shuffle itself was not
broken — measured 0.501 over 4000 seeds. Randomness streaks.

**What excludes it is the earlier session.** There, `carrier_pulse` appeared in
slot 0 four times and slot 1 twice, and she chose it all six times:

```
  a= 3 b= 9 order=[1,0]  chose slot 0 -> carrier_pulse   (slot 0)
  a= 9 b= 1 order=[1,0]  chose slot 1 -> carrier_pulse   (slot 1)
  a= 9 b= 7 order=[1,0]  chose slot 1 -> carrier_pulse   (slot 1)
  a= 9 b=16 order=[0,1]  chose slot 0 -> carrier_pulse   (slot 0)
  a= 9 b= 5 order=[0,1]  chose slot 0 -> carrier_pulse   (slot 0)
  a= 9 b=14 order=[0,1]  chose slot 0 -> carrier_pulse   (slot 0)
```

She tracked the same stimulus across both screen positions. A position bias
cannot produce that. Pooled catch trials point the other way as well — 3 of 3 on
the *first* interval, the opposite slot from the one she favoured on 2026-07-29
— though at n = 3 that is a hint, not a measurement.

So each session carries a confound the other excludes: the first was
level-confounded but position-clean, the second position-confounded but
level-clean. Together they support the finding; neither would alone.

## What was changed as a result

**Presentation order is now counterbalanced in blocks of two.** Each pair of
consecutive trials contains one `[0,1]` and one `[1,0]`, so slot imbalance is
bounded at one trial instead of being free to streak. Verified: imbalance 0
across 3000 simulated ten-trial sessions, against 6 in the real one. Applies to
the control trials too, where a slot bias would otherwise read as a level
effect.

The deeper lesson is the same one the level confound taught. An
information-gain selector concentrates on the current leader, so **any**
systematic advantage the leader happens to have gets amplified into a
clean-looking landslide. Level was the first instance. Position was the second.
Anything else that correlates with being the leader is a candidate for the
third, and the defence is a control that shares the artefact rather than a
belief that the artefact is absent.

## Status of the claim

**A signal worth pursuing, not an established result.** n = 11 presentations
across 2 sessions and 2 pools. Level excluded by construction and by control;
position excluded by cross-session tracking. Still unexcluded:

- **Audibility.** No audiogram exists. The simulation reaches the acoustic ear
  alone, so a frequency region that ear cannot hear is a region where no two
  candidates can differ. Pulse and noise carriers differ broadly across the
  spectrum, so this is unlikely to be the whole story, but it is not ruled out.
- **Only 1 catch trial** this session, so within-session response bias could not
  be checked. The 1-in-6 rate remains too sparse to calibrate anything quickly;
  the diagnostic pools across sessions and still has only 3.
- **Small n against a 20-candidate pool.** The posterior did not converge and
  should not be quoted as though it had.

## Plausibility

It agrees with the literature in a way worth noting rather than trusting.
Pulsatile carriers are the physically correct model of what an implant does, and
noise-band vocoders are known to be a convenience of the intelligibility
literature rather than a faithful percept model. A listener preferring the
pulsatile simulation as *closer to her own percept* is the expected direction.
Agreement that neat deserves the same scrutiny as a surprise — hence the
controls above.
