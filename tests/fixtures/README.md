# Test fixtures

This directory is **gitignored except for this file**. Audio fixtures are not
committed, for two reasons.

**Size.** Audio does not diff, does not compress usefully in git, and once
committed is effectively permanent.

**Privacy.** Research audio frequently contains recordings of human voices. A
public repository is not an appropriate place for a study participant's voice,
however brief the clip.

## Reference-simulator regression fixtures

`tests/test_reference_regression.py` validates PRELUDE's simulator against output
from an established reference implementation. Those tests **skip automatically**
when fixtures are absent, so the suite passes on a clean checkout.

To enable them, place matched pairs here:

```
tests/fixtures/
├── <name>_source.wav      # natural audio, the simulator input
├── <name>_reference.wav   # the reference simulator's output for that input
└── <name>.yaml            # the parameters used, in PRELUDE's config format
```

The `.yaml` must describe the settings the *reference* tool ran with, so that
PRELUDE is configured equivalently. Without it the comparison is meaningless.

### What the comparison should and should not expect

Do **not** expect sample-accurate agreement. Noise carriers use different random
seeds and different phase, so the waveforms will differ substantially while
sounding near-identical.

Compare in this order, the later measures mattering more than the earlier:

1. **Per-channel envelope correlation** — the primary measure, because envelopes
   are the information a real device transmits
2. Long-term average spectrum
3. Modulation spectrum

Reference tools often output at a fixed sample rate regardless of input;
resample before comparing.

### Stronger than matching absolutes: match a delta

If two reference outputs exist for the *same* source under *different* settings
(say 12 channels versus 22), verify that PRELUDE reproduces the direction and
rough magnitude of the difference between them. Reproducing a delta is a
considerably stronger test than reproducing an absolute, because it cancels
implementation details that are irrelevant to the question being asked.
