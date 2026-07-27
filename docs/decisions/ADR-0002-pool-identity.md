# ADR-0002 — A recorded judgement must carry the identity of what was heard

- **Date:** 2026-07-26
- **Status:** Accepted

## Context

The fitting loop records judgements as pairs of integers: candidate 9 was
preferred to candidate 3. The integers index the candidate pool that was
mounted when the listener answered.

That is only meaningful while the pool is fixed, and pools are rebuilt often —
they encode the current best guess at the listener's device, so every new fact
about that device changes them. Changing the anchor from 22 to 19 channels
re-derived every "fine variation" candidate and shifted eight indices. Index 9
stopped being the pulse carrier and became `env900`, a candidate that had not
existed when the listener sat down.

Rescoring across that boundary does not fail. It silently answers a different
question: "chose the pulse carrier 6 of 6" becomes "chose `env900` 6 of 6",
with no error raised and nothing in the record to contradict it.

A second, subtler version of the same problem: `/audio/` is served
`immutable` with a year-long `max-age`, because stimuli are supposed to be
regenerated under new names rather than edited. Two successive pools both
contained a `cand_anchor.wav`. A phone with a warm cache would have played the
old audio and had the choice scored against the new pool.

Neither of these is hypothetical. Both were live in the tree at the same time,
and an archive directory named `pool-v1-misattributed` turned out not to be
the pool behind either recorded session — it holds the right stimuli in the
wrong order.

The constraint that shapes the decision: **judgements come from one listener
with a progressive condition, and cannot be recollected.** A defect that
crashes costs an evening. A defect that quietly reattributes a judgement costs
the finding, and may never be noticed.

## Decision

**Three identities, each covering exactly what it claims, and a refusal rather
than a guess when they do not match.**

**1. `config_id` — which simulation.** A hash of the simulator parameters
alone. Two candidates sharing one came out of the same settings, whatever
either pool called them. This is what relates a candidate *across* pools.

**2. `render_id` — which audio.** A hash of `config_id` plus everything else
that determines the bytes: source clip, duration, sample rate, implant ear,
ear balance, presentation mode, segment length, and the pool's common level.
Stimulus filenames are built from this, so any change to the audio produces a
new URL and `immutable` caching stays safe.

The distinction earned itself immediately. Naming files by `config_id` alone,
two pools — one with the ear balance baked in, one without — produced
**identical filenames and an identical pool id for twenty genuinely different
stimuli.** Neither had been deployed, and the collision was found only by
hashing the files.

**3. `pool_id` — which set, in which order.** A hash over the ordered
`(name, render_id)` pairs. Written into `pool.json`, stamped on every session
at creation, and checked before scoring. A mismatch returns no posterior and
says why.

**Sessions are also self-describing.** Every trial already records both the
indices and the filenames served, so `scripts/resolve_session.py` recovers the
index-to-stimulus mapping from a session alone, with no pool present. This is
the recovery path for the two sessions recorded before pool identity existed,
and it is the authority when a pool on disk disagrees.

## Alternatives rejected

**Never rebuild the pool.** Correct in principle, unworkable here: the pool
encodes the current hypothesis about the device, and the whole point is to
revise it. This would trade a data-integrity risk for a research dead end.

**Migrate old sessions to new indices.** Requires knowing the mapping, which
is exactly what was missing. Where it *is* known it is not needed, and where
it is needed it would be a guess written into the permanent record.

**Store candidate names instead of indices.** Better, but names are edited for
human reasons and two pools can use one name for different configurations —
`cand_anchor` already meant three different sounds. It moves the ambiguity
rather than removing it.

**Warn and score anyway.** Rejected outright. A warning attached to a number
that looks authoritative loses to the number. The failure mode being defended
against is precisely one that produces plausible output.

## Consequences

- Rebuilding a pool invalidates prior sessions *for automatic scoring*, and
  says so. They remain fully interpretable via `resolve_session.py`; both
  pre-identity sessions resolve completely and self-consistently.
- Rebuilding with no changes is a no-op: identical inputs give identical ids,
  so caches are not churned.
- `pool.json` grows two short strings per candidate. Irrelevant next to the
  audio.
- Archives are never pruned, and a pool whose provenance is doubtful is
  annotated rather than deleted or renamed — see
  `archive/pool-v1-misattributed/MISNAMED-README.md`.

## The general rule

An artefact that something else points at must carry enough identity to detect
that the pointer has gone stale. The 2004-era tool's `.par` sidecars are why
its experiments are still interpretable two decades on, and their absence is
why the 2025 sweeps are not. This is the same lesson, applied to a pool.
