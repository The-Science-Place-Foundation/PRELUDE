"""Command-line entry point: ``prelude-simulate``.

Runs audio through the simulator and writes the result, together with a
provenance sidecar recording the configuration that produced it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audio import Audio, file_hash, load_audio, prepare_for_playback, save_audio
from .ci_sim import SimulatorConfig, simulate
from .config import load_simulator_config


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prelude-simulate",
        description="Simulate how audio sounds through a cochlear implant.",
        epilog=(
            "Output is loudness-normalised and peak-limited before writing. "
            "See docs/05-EVALUATION-PROTOCOL.md before using output in a "
            "listening study."
        ),
    )
    p.add_argument("input", type=Path, help="input audio file")
    p.add_argument("-o", "--output", type=Path, required=True, help="output WAV path")
    p.add_argument("-c", "--config", type=Path, help="YAML simulator config")

    g = p.add_argument_group("device parameters (override the config file)")
    g.add_argument("--channels", type=int, help="number of analysis bands (m)")
    g.add_argument("--selected", type=int, help="channels transmitted per frame (n)")
    g.add_argument("--low-freq", type=float, help="analysis low edge in Hz")
    g.add_argument("--high-freq", type=float, help="analysis high edge in Hz")
    g.add_argument("--spacing", choices=["greenwood", "erb"], help="band spacing")
    g.add_argument("--carrier", choices=["noise", "tone"], help="resynthesis carrier")
    g.add_argument("--rate", type=float, dest="stim_rate", help="stimulation rate in pps")
    g.add_argument("--seed", type=int, help="random seed, for reproducible output")

    p.add_argument(
        "--sample-rate", type=int, default=20000,
        help="working sample rate (default: 20000, which accommodates an 8.5 kHz "
             "analysis ceiling)",
    )
    p.add_argument(
        "--target-lufs", type=float, default=-23.0,
        help="integrated loudness target for the output (default: -23)",
    )
    p.add_argument("--no-normalise", action="store_true",
                   help="skip loudness normalisation. NOT for material a human will "
                        "hear; intended for downstream analysis only.")
    p.add_argument("-q", "--quiet", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.input.exists():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    config = load_simulator_config(args.config) if args.config else SimulatorConfig()

    overrides = {
        k: v
        for k, v in {
            "n_channels": args.channels,
            "n_selected": args.selected,
            "low_freq": args.low_freq,
            "high_freq": args.high_freq,
            "spacing": args.spacing,
            "carrier": args.carrier,
            "stimulation_rate_hz": args.stim_rate,
            "seed": args.seed,
        }.items()
        if v is not None
    }
    if overrides:
        from dataclasses import replace

        config = replace(config, **overrides)

    try:
        audio = load_audio(args.input, target_rate=args.sample_rate, mono=True)
        result = simulate(audio.samples, audio.sample_rate, config)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    samples = result.audio
    loudness_report = None
    if not args.no_normalise:
        samples, loudness_report = prepare_for_playback(
            samples, audio.sample_rate, target_lufs=args.target_lufs
        )
    else:
        peak = float(abs(samples).max())
        if peak > 0:
            samples = samples / peak * 0.99

    metadata = {
        "tool": "prelude-simulate",
        "input_file": args.input.name,
        "input_sha256": file_hash(args.input),
        "config_hash": config.hash(),
        "config": vars(config).copy(),
        "diagnostics": result.diagnostics(),
        "normalised": not args.no_normalise,
    }
    if loudness_report is not None:
        metadata["loudness"] = {
            "target_lufs": args.target_lufs,
            "output_lufs": round(loudness_report.output_lufs, 2),
            "gain_db": round(loudness_report.gain_db, 2),
            "true_peak_db": round(loudness_report.output_true_peak_db, 2),
            "limiter_engaged": loudness_report.limited,
        }

    save_audio(args.output, Audio(samples, audio.sample_rate), metadata=metadata)

    if not args.quiet:
        print(f"wrote {args.output}")
        print(f"  config {config.hash()}  {config.n_selected}-of-{config.n_channels} "
              f"@ {config.stimulation_rate_hz:.0f} pps")
        if loudness_report:
            print(f"  {loudness_report.summary()}")
        print(f"  {json.dumps(result.diagnostics())}")
        print(f"  provenance: {args.output.with_suffix('.json')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
