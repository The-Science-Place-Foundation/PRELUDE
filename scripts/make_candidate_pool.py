#!/usr/bin/env python3
# PRELUDE - cochlear implant audio simulation and pre-processing.
# Copyright (C) The Science Place Foundation and the PRELUDE contributors.
# Licensed under the GNU Affero General Public License v3.0 or later.
# See the LICENSE file, or <https://www.gnu.org/licenses/>.

"""Render a pool of candidate simulations, and the distances between them.

The fitting loop asks "which of these two is closer to what your implant makes
of it?", so the two things being compared must be **different simulations of the
same source** - not different source material, and not the same simulation at
different levels. A pool of near-identical candidates produces trials where
every honest answer is "they sound the same", which is exactly what happens if
calibration stimuli are used here by mistake.

Two things are written:

``<name>.wav``
    One dichotic file per candidate. The implanted ear hears the unmodified
    source; the acoustic ear hears that candidate's simulation of it. Levels are
    matched per ear.

``pool.json``
    The full pairwise perceptual distance matrix, plus each candidate's
    configuration. The server needs the matrix to run the posterior update and
    to choose informative comparisons, and computing it here means the container
    needs no numerical libraries at all.

Usage
-----
    python3 scripts/make_candidate_pool.py --source speech.wav \
        --implant-ear right -o pool/
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from prelude.audio import Audio, load_audio, prepare_for_playback, save_audio
from prelude.ci_sim import SimulatorConfig, simulate
from prelude.fitting import envelope_distance
from prelude.study import Ear, EarAssignment, PresentationMode, build_dichotic

SR = 20000


def candidate_configs() -> list[tuple[str, SimulatorConfig]]:
    """A spread of plausible devices, chosen to be audibly distinct.

    **A broad sweep is the wrong shape once an anchor is known.** An
    information-maximising sampler asks whichever comparison best separates its
    hypotheses, not whichever sounds best - so over a pool that spans the whole
    space, most trials compare two configurations that are both wrong. A
    listener experiences that as the simulations getting steadily worse, which
    is exactly what was reported after the first real session.

    Once a configuration is known to be close, the pool should cluster around
    it: fine variation near the anchor, with a few distant options retained so
    the fit can still be pulled away if the anchor is wrong.

    Spread matters more than realism at this stage. If two candidates differ
    only in a way the listener cannot hear, the trial comparing them costs a
    minute and returns nothing. These vary the parameters that dominate the
    percept - channel count, how many channels survive peak picking, carrier,
    envelope bandwidth, and current spread.

    Defaults elsewhere follow a Cochlear Nucleus platform: 22 electrodes,
    ACE-style peak picking, 900 pps.
    """
    base = dict(low_freq=300.0, high_freq=8500.0, seed=0)
    out: list[tuple[str, SimulatorConfig]] = []

    # ANCHOR: the listener's actual implant, from the medical records.
    # 22 intracochlear contacts, one dead, so 21 working. ACE peak picking,
    # 900 pps.
    #
    # This supersedes an earlier "21 implanted, 1-3 lost, ~19 usable", which
    # was a recollection rather than the file. She has MORE channels than was
    # modelled, and the old 19-channel anchor sits 0.315 from this one -
    # comparable to the median distance across the whole pool, so it was not
    # a small error.
    #
    # The dead contact is modelled as a place mismatch rather than a channel
    # count: the processor reallocates the frequency range across the 21 live
    # contacts, but cannot move them, so a band is delivered roughly two
    # semitones from where its frequency belongs. See SimulatorConfig.
    array = dict(n_electrodes=22, electrode_numbering="basal_first")
    anchor = dict(n_channels=21, n_selected=8, carrier="noise",
                  envelope_cutoff_hz=300.0, interaction_decay_db=8.0,
                  stimulation_rate_hz=900.0, deactivated_electrodes=(2,),
                  **array, **base)
    out.append(("anchor", SimulatorConfig(**anchor)))

    # WHICH contact is dead is unresolved: the file numbers it "#2" but calls
    # it the second most distal, and on a Cochlear array the distal end is the
    # apex, whose second contact is 21. The two readings are 17x apart in
    # frequency - about 6457-7410 Hz against 364-438 Hz.
    #
    # Rather than guess, ask. The two simulations are 0.329 apart, well clear
    # of the 0.05 floor below which this procedure cannot separate anything,
    # so the listener's judgements can settle it. That is what the fit is for.
    out.append(("dead_apical", SimulatorConfig(**{**anchor, "deactivated_electrodes": (21,)})))
    # And whether modelling the dead contact matters at all: same 21 channels,
    # evenly spaced, no place mismatch. 0.153 from the anchor, so separable.
    out.append(("dead_ignored", SimulatorConfig(**{
        k: v for k, v in anchor.items()
        if k not in ("deactivated_electrodes", "n_electrodes", "electrode_numbering")})))
    # The array as implanted, before the contact failed.
    out.append(("intact22", SimulatorConfig(**{
        **{k: v for k, v in anchor.items()
           if k not in ("deactivated_electrodes", "n_electrodes", "electrode_numbering")},
        "n_channels": 22})))

    # Fine variation around the anchor: one parameter moved at a time, so a
    # preference points at a parameter rather than at an unattributable blend.
    #
    # Deliberately fewer than before. Simulated against the previous pool,
    # whether the true candidate is recovered was predicted almost entirely by
    # its nearest-neighbour distance - 5-6 runs in 6 when the nearest was 0.19
    # or further, 0-3 within 0.07 - and rate500/rate1800/spread4/spread16/
    # env900 all sat within 0.05 of the anchor. Those trials cost a minute
    # each and could not have returned anything.
    #
    # This is NOT the earlier mistake of pruning on a metric's say-so. That
    # metric was demonstrably blind: it smoothed at 50 Hz while being asked
    # about envelope bandwidths up to 900 Hz. This one analyses at 50/200/800
    # Hz, and its verdict has been checked against actual recovery rates in
    # simulation rather than assumed. The dropped configurations are recorded
    # here so the decision is reversible:
    #
    #   rate500 (0.065), rate1800 (0.037), spread4 (0.034), spread16 (0.033),
    #   env900 (0.021)  - all distances to the old anchor.
    #
    # If she can hear a difference these do not capture, the metric is wrong
    # and they come back. Her judgements decide that, not the matrix.
    for n_sel in (6, 10, 12):
        out.append((f"maxima{n_sel}", SimulatorConfig(**{**anchor, "n_selected": n_sel})))
    out.append(("env80", SimulatorConfig(**{**anchor, "envelope_cutoff_hz": 80.0})))
    for carrier in ("pulse", "tone"):
        out.append((f"carrier_{carrier}", SimulatorConfig(**{**anchor, "carrier": carrier})))

    # A few distant options kept deliberately, so the fit can still be pulled
    # away if the anchor turns out to be wrong. Without these the pool could
    # only ever confirm its own starting point.
    plain = {k: v for k, v in anchor.items()
             if k not in ("deactivated_electrodes", "n_electrodes", "electrode_numbering")}
    for n in (6, 8, 12, 16):
        out.append((f"ch{n:02d}", SimulatorConfig(**{**plain, "n_channels": n, "n_selected": n})))

    # Retained because the listener has already been asked about them.
    # Dropping a configuration that appears in a recorded judgement orphans
    # that judgement: it can no longer be scored against the pool, and the
    # listening time that produced it is simply lost. Candidates may be added
    # freely; removing one has a cost paid in someone else's evenings.
    out.append(("maxima4", SimulatorConfig(**{**anchor, "n_selected": 4})))
    out.append(("carrier_pulse_loose",
                SimulatorConfig(**{**anchor, "carrier": "pulse", "synchronization": 0.5})))

    names = [n for n, _ in out]
    if len(names) != len(set(names)):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"duplicate candidate name(s) {dupes}; names index judgements")

    return out


def _archive_existing(out: Path) -> None:
    """Move any existing pool aside instead of overwriting it.

    **A pool is not scratch output.** It is the reference every recorded
    judgement points at: a session stores which candidates were compared, so
    discarding the pool discards the meaning of the sessions scored against it.
    Regenerating over the top of one already orphaned four of five real
    judgements from a listener who does not have unlimited evenings.

    Archives are never pruned. They are small next to what they protect.
    """
    if not out.exists() or not any(out.iterdir()):
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = out.parent / "archive" / f"{out.name}-{stamp}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(out), str(dest))
    print(f"archived the previous pool to {dest}")


def _find_prior_asset(out: Path, name: str) -> Path | None:
    """Existing copy of a fixed-name asset the app depends on.

    The live pool is checked first, and that is the actual guarantee: building
    a new pool beside a live one is the normal case, and the live one is where
    these assets are.

    Archives are the fallback, ordered by modification time rather than name.
    Name order does not work: most archives are stamped
    ``<pool>-<UTC timestamp>``, but at least one is hand-named
    (``pool-v1-misattributed``), and ``-`` sorts below ``_``, so a reverse
    name sort puts every ``pool_new-*`` ahead of every ``pool-*`` whatever the
    dates say.
    """
    roots = [out.parent / "pool"]
    archive = out.parent / "archive"
    if archive.is_dir():
        roots.extend(sorted((d for d in archive.iterdir() if d.is_dir()),
                            key=lambda d: d.stat().st_mtime, reverse=True))
    for d in roots:
        f = d / name
        if d != out and f.is_file():
            return f
    return None


def _config_id(cfg: SimulatorConfig) -> str:
    """Short stable hash of the simulator parameters behind a candidate.

    Two candidates with the same id came out of the same simulator settings
    regardless of what either pool called them, which is what lets a
    judgement recorded against one pool be related to another.

    This deliberately covers the *simulation* only. It is not sufficient to
    identify the audio - see :func:`_render_id`.
    """
    # Every parameter that varies between candidates has to appear here. Three
    # candidates in this pool differ ONLY in which contact is dead - anchor,
    # dead_apical and dead_ignored are all 21 channels otherwise - so omitting
    # the deactivation fields would give three different sounds one identity,
    # and through it one filename and one entry in the record.
    keys = ("n_channels", "n_selected", "carrier", "stimulation_rate_hz",
            "envelope_cutoff_hz", "interaction_decay_db", "synchronization",
            "low_freq", "high_freq", "spacing",
            "n_electrodes", "deactivated_electrodes", "electrode_numbering")
    g = vars(cfg)
    blob = json.dumps({k: g.get(k) for k in keys}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:10]


def _render_id(cfg: SimulatorConfig, presentation: dict) -> str:
    """Hash of everything that determines the actual bytes of a stimulus.

    The simulator config alone does not. The same simulation rendered at a
    different ear balance, segment length, source clip or pool level is
    different audio, and naming files by simulator config alone put two
    genuinely different builds at identical filenames with identical ids -
    while ``/audio/`` serves them ``immutable`` for a year.

    Caught before either build was deployed, but only by measuring: a pool
    rendered with the balance baked in and one without shared all twenty
    filenames and the same pool id. Whatever changes the bytes has to change
    the name.
    """
    blob = json.dumps({"config": _config_id(cfg), **presentation},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:10]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True,
                    help="speech or music clip to simulate")
    ap.add_argument("--implant-ear", choices=["left", "right"], required=True)
    ap.add_argument("-o", "--output", type=Path, default=Path("pool"))
    ap.add_argument("--seconds", type=float, default=6.0,
                    help="clip length; short keeps each trial brief")
    ap.add_argument("--balance-db", type=float, default=0.0,
                    help="implant-ear level offset from calibration")
    ap.add_argument("--control-db", type=float, default=3.0,
                    help="level difference for the control pair. Defaults to the "
                         "3 dB gap that confounded the first session.")
    ap.add_argument("--min-distance", type=float, default=0.02,
                    help="drop candidates closer than this to one already kept. "
                         "Deliberately low: it should catch near-duplicates, not "
                         "decide which parameters matter. See the note below.")
    args = ap.parse_args()

    out = args.output
    _archive_existing(out)
    out.mkdir(parents=True, exist_ok=True)
    assignment = EarAssignment(implant_ear=Ear(args.implant_ear))

    src = load_audio(args.source, target_rate=SR, mono=True).samples
    src = src[: int(args.seconds * SR)]

    configs = candidate_configs()
    print(f"rendering {len(configs)} candidates from {args.source.name}")

    # Render everything first, then find a level that ALL candidates can reach
    # without the peak limiter engaging.
    #
    # Normalising each file independently makes high-crest candidates quieter
    # than the rest: the limiter pulls them down and nothing notices. In the
    # first real session the pulse-carrier candidate sat 3.09 dB below the
    # other sixteen, which spanned 0.20 dB between them - and the listener
    # chose it in six of six trials. "Preferred the pulse carrier" and
    # "preferred the quieter interval" then predict identical data, and the
    # session cannot separate them. Three dB is around three times a level
    # just-noticeable-difference.
    sims = [simulate(src, SR, cfg).audio for _, cfg in configs]
    achievable = []
    for sim in sims:
        _, rep = prepare_for_playback(sim, SR)
        achievable.append(rep.output_lufs)
    common = min(achievable)
    print(f"levelling the pool to {common:.2f} LUFS "
          f"(worst case of {len(sims)}; spread was {max(achievable) - common:.2f} dB)")

    # Everything outside the simulator config that changes the rendered bytes.
    # Part of the filename and of the pool id, so a rebuild under different
    # presentation cannot reuse either.
    presentation = {
        "source": args.source.name,
        "seconds": args.seconds,
        "sample_rate": SR,
        "implant_ear": assignment.implant_ear.value,
        "balance_db": args.balance_db,
        "mode": PresentationMode.ALTERNATING.value,
        "segment_ms": 500,
        "common_lufs": round(common, 3),
    }

    entries, audio = [], []
    for i, (name, cfg) in enumerate(configs):
        sim = sims[i]
        audio.append(sim)
        d = build_dichotic(
            src, sim, SR, assignment,
            mode=PresentationMode.ALTERNATING, segment_ms=500,
            implant_target_lufs=common + args.balance_db,
            acoustic_target_lufs=common,
        )
        # The filename carries the config hash. Two pools each had a
        # ``cand_anchor.wav`` holding different audio, and /audio/ is served
        # ``immutable`` with a year-long max-age - a phone with a warm cache
        # would have played the old sound and had the choice scored as the
        # new one. A name that changes whenever the audio changes makes that
        # failure impossible rather than merely unlikely.
        cid = _config_id(cfg)
        rid = _render_id(cfg, presentation)
        fname = f"cand_{name}-{rid}.wav"
        save_audio(out / fname, Audio(d.samples, SR))
        entries.append({
            "index": i, "name": name, "file": fname,
            # Identity follows the configuration, not the label. Names are for
            # humans and get edited; a recorded judgement has to stay
            # resolvable when they do.
            "config_id": cid,
            # Identity of the audio itself, presentation included.
            "render_id": rid,
            "config": {k: v for k, v in vars(cfg).items()},
            "duration_s": round(d.duration_s, 2),
        })
        print(f"  {i + 1:2d}/{len(configs)}  {fname}")

    # Pairwise perceptual distance, on channel envelopes rather than waveforms:
    # envelopes are what an implant transmits, so two signals with matching
    # envelopes sound alike through one however different their samples look.
    n = len(audio)
    dist = [[0.0] * n for _ in range(n)]
    print("computing pairwise distances...")
    for i, j in itertools.combinations(range(n), 2):
        d = float(envelope_distance(audio[i], audio[j], SR))
        dist[i][j] = dist[j][i] = d

    # Greedily drop near-duplicates only.
    #
    # The threshold is deliberately low. An earlier run pruned at 0.08 and
    # discarded stimulation rate, interaction decay and envelope bandwidth as
    # "indistinguishable" - but the measure could not resolve those parameters
    # in the first place, so the result said nothing about whether a listener
    # could hear them. A distance below threshold means the metric cannot
    # separate two candidates; it does not mean a person cannot. Deciding on
    # the listener's behalf, using an instrument known to be blind in that
    # range, removes exactly the comparisons that would have settled the
    # question.
    #
    # Pruning is for genuine duplicates. Which parameters matter is for the
    # listener to answer.
    keep: list[int] = []
    for i in range(n):
        if all(dist[i][j] >= args.min_distance for j in keep):
            keep.append(i)
    dropped = [entries[i]["name"] for i in range(n) if i not in keep]
    if dropped:
        print(f"\npruned {len(dropped)} indistinguishable candidate(s): "
              f"{', '.join(dropped)}")
        for i in range(n):
            if i not in keep:
                (out / entries[i]["file"]).unlink(missing_ok=True)
        entries = [entries[i] for i in keep]
        for new_idx, e in enumerate(entries):
            e["index"] = new_idx
        dist = [[dist[i][j] for j in keep] for i in keep]
        n = len(keep)

    # ---- level control pair -------------------------------------------
    # The anchor against an attenuated copy of ITSELF. Identical content;
    # level is the only difference. If the listener reliably picks the quieter
    # one, then a preference correlated with level explains itself and no
    # carrier claim survives.
    #
    # This is the cheapest measurement that decides the question, and it does
    # not depend on the levelling above being correct - which is exactly why
    # it is worth having.
    # ``sims`` is the unpruned list and ``entries`` is the pruned one, so an
    # index into one is not an index into the other. Look the anchor up by
    # name in both. This was benign only while the anchor sat at index 0 and
    # index 0 was always kept; it would have silently rendered the control
    # from the wrong candidate the moment either stopped being true.
    sim_by_name = {name: sims[i] for i, (name, _) in enumerate(configs)}
    ctrl = build_dichotic(
        src, sim_by_name["anchor"], SR, assignment,
        mode=PresentationMode.ALTERNATING, segment_ms=500,
        implant_target_lufs=common + args.balance_db,
        acoustic_target_lufs=common,
    )
    ctrl_id = _render_id(dict(configs)["anchor"], presentation)
    ref_name = f"control_level_ref-{ctrl_id}.wav"
    quiet_name = f"control_level_quiet-{ctrl_id}.wav"
    save_audio(out / ref_name, Audio(ctrl.samples, SR))
    quiet = ctrl.samples * (10.0 ** (-args.control_db / 20.0))
    save_audio(out / quiet_name, Audio(quiet, SR))
    print(f"level control pair written: identical content, "
          f"{args.control_db:.0f} dB apart")

    # ---- assets the app fetches by fixed name --------------------------
    # The calibration stimuli are built by make_calibration_session.py and
    # live alongside the pool because the app serves everything from one
    # directory. A pool without them silently breaks the channel check and
    # the balance staircase - the balance measurement this pool's own levels
    # are built on. Carry them forward from the pool being replaced.
    for asset in ("channel_check.wav", "balance_source.wav"):
        if (out / asset).is_file():
            continue
        prior = _find_prior_asset(out, asset)
        if prior is None:
            print(f"  WARNING: {asset} is missing and no previous pool has it.")
            print("           The app fetches it by name; calibration will fail.")
            print("           Run scripts/make_calibration_session.py.")
            continue
        shutil.copy2(prior, out / asset)
        print(f"  carried forward {asset} from {prior.parent.name}")

    flat = [dist[i][j] for i, j in itertools.combinations(range(n), 2)]
    pool_body = {
        # Presented before the candidate trials. Identical audio at two levels,
        # so any consistent preference measures sensitivity to level rather
        # than to anything the simulator varies.
        "control_pair": {
            "files": [ref_name, quiet_name],
            "difference_db": args.control_db,
            "duration_s": round(ctrl.duration_s, 2),
            "purpose": "does a level difference alone drive the choice?",
        },
        "source": args.source.name,
        "sample_rate": SR,
        "implant_ear": assignment.implant_ear.value,
        "balance_db": args.balance_db,
        "candidates": entries,
        "distances": dist,
    }

    # ---- pool identity -------------------------------------------------
    # A session record stores bare integers. Those integers only mean
    # something relative to the pool that was mounted when they were
    # recorded, and rebuilding the pool reorders them: changing the anchor
    # from 22 to 19 channels moved candidate 9 from the pulse carrier to a
    # candidate that had not existed, so re-scoring an existing session would
    # have quietly reattributed six of seven judgements to the wrong sound.
    #
    # The id covers what a judgement depends on - which sounds, in which
    # order - so any pool that would reinterpret an index gets a different
    # one and the server can refuse the mismatch instead of scoring it.
    identity = json.dumps(
        [[e["name"], e["render_id"]] for e in entries], sort_keys=True)
    pool_body["pool_id"] = hashlib.sha256(identity.encode()).hexdigest()[:12]
    (out / "pool.json").write_text(json.dumps(pool_body, indent=2, default=str))

    print(f"\nwrote {out}/pool.json  (pool_id {pool_body['pool_id']})")
    print(f"  distance spread: min {min(flat):.3f}  median "
          f"{sorted(flat)[len(flat) // 2]:.3f}  max {max(flat):.3f}")
    if min(flat) > 0.05:
        print("  every pair is audibly distinct - good")
    else:
        near = sum(1 for d in flat if d < 0.05)
        print(f"  WARNING: {near} pair(s) nearly identical; those trials will "
              f"cost a minute and return nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
