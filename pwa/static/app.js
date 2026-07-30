/* PRELUDE listening companion.
   Copyright (C) The Science Place Foundation and the PRELUDE contributors.
   Licensed under the GNU Affero General Public License v3.0 or later.

   Web Audio, not <audio> elements, for three reasons that all matter here:

   1. On iOS an <audio> element is silenced by the physical ringer switch.
      A session that plays nothing, with no visible cause, is a baffling
      failure mode for a listener to hit alone.
   2. Alternating presentation needs sample-accurate scheduling. A ragged
      segment boundary is audible as a click, and a click is both unpleasant
      and an unintended cue about which ear is active.
   3. The balance offset is applied here, per ear, at playback. That gives
      arbitrary precision from a single file rather than a pre-rendered grid,
      and it means one measured calibration governs every later stimulus
      without re-rendering anything.

      Only the RESIDUAL is applied: a pool can be rendered with part of the
      offset already baked in, and the server reports how much via
      pool_balance_db. Applying the full measured value on top of a pool
      rendered at +6 dB would have put the ears 12 dB apart against a balance
      measured at 6.

   Stereo is preserved end to end: the file's left channel reaches the left
   device and the right reaches the right. Nothing mixes to mono, because the
   whole comparison depends on the ears staying separate. */

/* Alternation period of the rendered stimuli. Kept in step with
   scripts/make_candidate_pool.py, which renders at 500 ms segments. */
const SEGMENT_MS = 500;

/* Which ear holds the implant. Getting this backwards would apply the balance
   correction to the wrong side. */
const IMPLANT_EAR = 'right';

const S = {
  sessionId: null, trial: null, maxTrials: 40,
  shownAt: 0, playing: false, buffers: new Map(), ctx: null,
  answered: 0, sameCount: 0, heard: false,
  balanceDb: 0, residualDb: 0, calibrated: false, channelsSeparate: false,
  bal: null,
};

const $ = (id) => document.getElementById(id);
const views = [...document.querySelectorAll('.view')];
const show = (name) =>
  views.forEach(v => v.classList.toggle('hidden', v.dataset.view !== name));

/* ------------------------------------------------------------------ audio */

// Created on the first user gesture: iOS will not start an AudioContext
// without one, and an unlocked context is required before any playback.
function audioCtx() {
  if (!S.ctx) S.ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (S.ctx.state === 'suspended') S.ctx.resume();
  return S.ctx;
}

async function loadBuffer(name) {
  if (S.buffers.has(name)) return S.buffers.get(name);
  const res = await fetch(`/audio/${encodeURIComponent(name)}`);
  if (!res.ok) throw new Error(`could not load ${name}`);
  const buf = await audioCtx().decodeAudioData(await res.arrayBuffer());
  S.buffers.set(name, buf);
  return buf;
}

/**
 * Play a stereo buffer, optionally offsetting one ear.
 *
 * `implantDb` raises the implant side relative to the other. It is applied by
 * ATTENUATING the opposite ear rather than boosting the implant ear, so the
 * signal never exceeds the level it was rendered and peak-limited at. Boosting
 * would quietly undo the ceiling the file was written under.
 */
function playBuffer(buf, implantDb = 0) {
  return new Promise((resolve) => {
    const ctx = audioCtx();
    const src = ctx.createBufferSource();
    src.buffer = buf;

    if (!implantDb || buf.numberOfChannels < 2) {
      src.connect(ctx.destination);
    } else {
      const split = ctx.createChannelSplitter(2);
      const merge = ctx.createChannelMerger(2);
      const gL = ctx.createGain(), gR = ctx.createGain();
      const cut = Math.pow(10, -Math.abs(implantDb) / 20);
      const implantIsRight = IMPLANT_EAR === 'right';
      if (implantDb > 0) {          // implant louder: bring the other ear down
        gL.gain.value = implantIsRight ? cut : 1;
        gR.gain.value = implantIsRight ? 1 : cut;
      } else {                      // implant quieter: bring the implant down
        gL.gain.value = implantIsRight ? 1 : cut;
        gR.gain.value = implantIsRight ? cut : 1;
      }
      src.connect(split);
      split.connect(gL, 0); split.connect(gR, 1);
      gL.connect(merge, 0, 0); gR.connect(merge, 0, 1);
      merge.connect(ctx.destination);
    }
    src.onended = resolve;
    src.start();
  });
}

/** Light the ear indicators in step with the alternation. */
function earSweep(leadRight) {
  const l = $('dotL'), r = $('dotR');
  (leadRight ? r : l).classList.add('on');
  return setInterval(() => {
    l.classList.toggle('on'); r.classList.toggle('on');
  }, SEGMENT_MS);
}
const earsOff = (...ids) => ids.forEach(i => $(i).classList.remove('on'));

/* ------------------------------------------------------------- api + moon */

async function api(path, body) {
  const res = await fetch(path, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  } : {});
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function paintMoon(done, total) {
  const frac = Math.max(0, Math.min(1, total ? done / total : 0));
  $('moonFill').style.clipPath = `inset(0 ${(1 - frac) * 100}% 0 0)`;
  const names = ['The new moon', 'The thin crescent', 'The waxing half',
                 'The gibbous', 'The full moon'];
  $('moonName').textContent = names[Math.min(4, Math.floor(frac * 4.999))];
}

/* --------------------------------------------------- calibration: channels */

function startChannelCheck() {
  audioCtx();
  show('channels');
  $('chanYes').disabled = $('chanNo').disabled = true;
}

$('chanPlay').addEventListener('click', async () => {
  $('chanPlay').disabled = true;
  try {
    const buf = await loadBuffer('channel_check.wav');
    // Left only, right only, then both. The indicators follow the file so a
    // mono collapse is visible as well as audible.
    [[0, 'cdL'], [2000, 'cdR'], [4000, null]].forEach(([ms, id]) =>
      setTimeout(() => {
        earsOff('cdL', 'cdR');
        if (id) $(id).classList.add('on');
        else { $('cdL').classList.add('on'); $('cdR').classList.add('on'); }
      }, ms));
    await playBuffer(buf);
    earsOff('cdL', 'cdR');
    $('chanYes').disabled = $('chanNo').disabled = false;
  } catch {
    show('trouble');
  } finally {
    $('chanPlay').disabled = false;
    $('chanPlay').textContent = 'Play again';
  }
});

$('chanYes').addEventListener('click', () => startBalance());
$('chanNo').addEventListener('click', () => {
  // A path that collapses to mono makes every later judgement meaningless
  // while still sounding perfectly plausible. Stop rather than collect it.
  $('troubleTitle').textContent = 'Both ears are getting the same thing.';
  $('troubleNote').textContent =
    'Something between the phone and the devices is mixing the two sides ' +
    'together. Nothing measured this way would mean anything, so it is ' +
    'better to stop and sort that out first.';
  show('trouble');
});

/* -------------------------------------------------- calibration: balance */

/* A staircase rather than a fixed sweep of offsets.
   It approaches the balance point from both sides and takes its answer from
   the reversals, so it does not require the listener's responses to be
   monotonic - which, with a task this subtle, they will not be. A fixed sweep
   asked seven questions and produced an unusable answer for exactly that
   reason. */
function startBalance() {
  audioCtx();
  S.bal = { offset: 0, step: 6, dir: 0, reversals: [], responses: [],
            centred: [], probe: -1, n: 0 };
  show('balance');
  $('balFoot').textContent = 'Eight short listens · press listen to start';
  $('balPlay').textContent = 'Listen';
  balButtons(true);
}

const balButtons = (dis) =>
  ['balLeft', 'balMid', 'balRight'].forEach(id => { $(id).disabled = dis; });

$('balPlay').addEventListener('click', async () => {
  $('balPlay').disabled = true;
  balButtons(true);
  try {
    const buf = await loadBuffer('balance_source.wav');
    await playBuffer(buf, S.bal.offset);
    balButtons(false);
    $('balFoot').textContent = `${S.bal.n + 1} of 8 · which way did it pull?`;
  } catch {
    show('trouble');
  } finally {
    $('balPlay').disabled = false;
    $('balPlay').textContent = 'Listen again';
  }
});

function balanceRespond(kind) {
  const b = S.bal;
  b.n++;
  b.responses.push({ offset: b.offset, said: kind });

  let dir = 0;
  if (kind === 'left') { dir = +1; b.offset += b.step; }
  else if (kind === 'right') { dir = -1; b.offset -= b.step; }
  else {
    b.centred.push(b.offset);
    // "Centred" alone proves nothing: the first calibration answered
    // "middle" three times without the offset ever leaving zero, and
    // returned 0 dB having never tested whether +6 or -6 also felt
    // centred. Deliberately step away to find where it stops feeling
    // centred - that edge is the measurement.
    b.probe = -(b.probe || -1);
    b.offset += b.probe * b.step;
  }

  // A reversal means the balance point has been bracketed; narrow the step.
  if (dir && b.dir && dir !== b.dir) {
    b.reversals.push(b.offset);
    b.step = Math.max(1, b.step / 2);
  }
  if (dir) b.dir = dir;
  b.offset = Math.max(-18, Math.min(18, b.offset));

  // Requires reversals - actual bracketing - or the trial ceiling. Counting
  // "centred" answers as sufficient is what let the first calibration finish
  // without measuring anything.
  // Eight trials, not twelve. Simulated against 200 listeners at several true
  // balance points, twelve gave 0.3-0.9 dB accuracy and eight gave 0.3-1.3 dB
  // - a third less of a tedious task for an error well below anything that
  // matters downstream. The listener's willingness to keep doing this is a
  // real constraint, and spending it on precision we do not need is a bad
  // trade.
  if (b.reversals.length >= 4 || b.n >= 8) {
    finishBalance(false);
    return;
  }
  balButtons(true);
  $('balFoot').textContent = `${b.n} of 8 · press listen for the next`;
  $('balPlay').textContent = 'Listen';
}

$('balLeft').addEventListener('click', () => balanceRespond('left'));
$('balMid').addEventListener('click', () => balanceRespond('mid'));
$('balRight').addEventListener('click', () => balanceRespond('right'));
$('balStop').addEventListener('click', () => finishBalance(true));

async function finishBalance(early) {
  const b = S.bal;
  // Reversals are the measurement. Centred answers are included only when
  // reversals exist to bracket them - otherwise they are one point repeated.
  const pts = b.reversals.length ? [...b.reversals, ...b.centred] : [];
  const value = pts.length
    ? Math.round((pts.reduce((a, c) => a + c, 0) / pts.length) * 10) / 10
    : null;

  if (value !== null) { S.balanceDb = value; S.residualDb = value - (S.poolBalanceDb || 0); }
  try {
    await api('/api/calibration', {
      balance_db: value, channels_separate: true,
      reversals: b.reversals, responses: b.responses,
    });
    S.calibrated = value !== null;
  } catch { /* it still applies to this session */ }

  $('doneTitle').textContent = value === null
    ? 'Stopped before it settled.'
    : 'Balance found.';
  $('doneNote').textContent = value === null
    ? 'Nothing saved. It can be done another time.'
    : `${value > 0 ? '+' : ''}${value} dB on the implant side, from ` +
      `${b.n} listening${b.n === 1 ? '' : 's'}. Every comparison from here ` +
      `will use it.`;
  paintMoon(early ? 1 : 4, 4);
  show('done');
}

/* -------------------------------------------------------------- comparing */

async function playTrial() {
  if (S.playing || !S.trial) return;
  S.playing = true;
  $('listenBtn').disabled = true;
  $('cardA').disabled = $('cardB').disabled = true;

  const [i, j] = S.trial.presentation_order;
  const names = [S.trial.options[i], S.trial.options[j]];
  const cards = [$('cardA'), $('cardB')];

  try {
    const bufs = await Promise.all(names.map(loadBuffer));
    for (let k = 0; k < 2; k++) {
      cards[k].classList.add('sounding');
      const sweep = earSweep(IMPLANT_EAR === 'right');
      await playBuffer(bufs[k], S.residualDb);
      clearInterval(sweep);
      earsOff('dotL', 'dotR');
      cards[k].classList.remove('sounding');
      if (k === 0) await new Promise(r => setTimeout(r, 420));
    }
    S.heard = true;
    S.shownAt = performance.now();   // deliberation time, not screen time
    $('cardA').disabled = $('cardB').disabled = false;
    $('sameBtn').disabled = false;
    $('trialFoot').textContent = 'Choose whichever felt closer';
  } catch {
    $('troubleNote').textContent =
      'That sound could not be loaded. The library may be unreachable.';
    show('trouble');
  } finally {
    S.playing = false;
    $('listenBtn').disabled = false;
    $('listenBtn').textContent = 'Listen again';
  }
}

async function begin() {
  audioCtx();
  try {
    const data = await api('/api/session');
    S.sessionId = data.session_id;
    S.maxTrials = data.max_trials;
    S.trial = data.trial;
    S.answered = 0;
    if (!S.trial) {
      $('troubleNote').textContent =
        'There are no sounds in the library yet. Nothing to listen to.';
      show('trouble');
      return;
    }
    show('ritual');
  } catch {
    show('trouble');
  }
}

/* No enforced settle before comparing: the 30-second wait belongs to
   calibration, where a device is physically removed and loudness perception
   drifts afterwards. This flow asks for no device change. */

function enterTrial() {
  show('trial');
  S.shownAt = 0;                 // starts when the audio finishes, not now
  S.heard = false;
  $('listenBtn').textContent = 'Listen';
  $('trialFoot').textContent = 'Listen to both, then choose';
  // Locked until both candidates have actually played. In the first real
  // session two of six responses arrived in under two seconds - less time
  // than a single stimulus takes - and those taps fed the posterior as
  // though they were judgements. A choice made before hearing anything is
  // not a weak data point, it is a wrong one.
  $('cardA').disabled = $('cardB').disabled = true;
  $('sameBtn').disabled = true;
}

async function respond(choice) {
  if (S.playing || !S.trial || !S.heard) return;
  const ms = Math.round(performance.now() - S.shownAt);
  if (choice === 'same') S.sameCount++;
  S.answered++;
  const payload = {
    session_id: S.sessionId, trial_id: S.trial.trial_id,
    chose: choice, response_ms: ms,
  };
  stash(payload);
  try {
    const data = await api('/api/respond', payload);
    S.trial = data.trial;
    if (!S.trial) { finish(false); return; }
    enterTrial();
  } catch {
    show('trouble');
  }
}

async function finish(early) {
  try {
    await api('/api/finish', { session_id: S.sessionId, ended_early: early });
  } catch { /* the local stash still holds it */ }
  const n = S.answered;
  $('doneTitle').textContent = early
    ? 'Stopping here is a good call.'
    : 'That’s enough for tonight.';
  $('doneNote').textContent = n === 0
    ? 'Nothing tonight, and that is fine.'
    : `${n} listening${n === 1 ? '' : 's'}. ` +
      (S.sameCount
        ? `${S.sameCount} of them felt the same to you, which tells us as much as the rest.`
        : 'Every one of them told us something.');
  paintMoon(n, S.maxTrials);
  show('done');
}

/* Local copy in case the server is unreachable mid-session. Safari can evict
   script-writable storage, so this is a safety net and not the record. */
function stash(obj) {
  try {
    const key = 'prelude.pending';
    const all = JSON.parse(localStorage.getItem(key) || '[]');
    all.push({ ...obj, at: new Date().toISOString() });
    localStorage.setItem(key, JSON.stringify(all.slice(-500)));
  } catch { /* not worth interrupting a session over */ }
}

/* ------------------------------------------------------------------ wire */

$('settleBtn').addEventListener('click', enterTrial);
$('listenBtn').addEventListener('click', playTrial);
$('cardA').addEventListener('click', () => respond(0));
$('cardB').addEventListener('click', () => respond(1));
$('sameBtn').addEventListener('click', () => respond('same'));
$('stopBtn').addEventListener('click', () => finish(true));
$('closeBtn').addEventListener('click', () => location.reload());
$('retryBtn').addEventListener('click', () => location.reload());

(async function boot() {
  try {
    const [h, c] = await Promise.all([api('/health'), api('/api/calibration')]);
    const cal = c.calibration;
    /* How much of the balance the stimuli already carry. Stored before any
       residual is derived, because finishBalance() recomputes the residual
       after a fresh measurement and would otherwise subtract undefined and
       reapply the whole offset on top of a pool that already has it. */
    S.poolBalanceDb = c.pool_balance_db || 0;
    if (cal && typeof cal.balance_db === 'number') {
      S.balanceDb = cal.balance_db;
      /* Apply only the part the stimuli do not already carry. Applying the
         measured value on top of a pool rendered at +6 dB would put the ears
         12 dB apart against a balance measured at 6. */
      S.residualDb = S.balanceDb - S.poolBalanceDb;
      S.calibrated = true;
    }
    S.channelsSeparate = !!(cal && cal.channels_separate);
    const sessions = h.sessions_on_disk;

    if (!S.calibrated) {
      // Steer toward calibration without blocking. An uncalibrated session is
      // still informative; it just carries a level confound.
      $('moonNote').textContent =
        'The balance has not been tuned yet. That comes first — everything ' +
        'after it leans on getting it right.';
      $('beginBtn').textContent = 'Tune the balance';
      $('beginBtn').addEventListener('click', startChannelCheck);
      $('tuneBtn').textContent = 'Skip, and just listen';
      $('tuneBtn').addEventListener('click', begin);
    } else {
      const sign = S.balanceDb > 0 ? '+' : '';
      $('moonNote').textContent = sessions
        ? `${sessions} listening${sessions === 1 ? '' : 's'} gathered. ` +
          `Balance held at ${sign}${S.balanceDb} dB.`
        : `Balance is tuned to ${sign}${S.balanceDb} dB. Nothing gathered yet.`;
      $('tuneBtn').textContent = 'Tune the balance again';
      $('beginBtn').addEventListener('click', begin);
      $('tuneBtn').addEventListener('click', startChannelCheck);
    }
    paintMoon(Math.min(sessions, 12), 12);
  } catch {
    show('trouble');
  }
})();


/* ------------------------------------------------------ mapping session */

/* Measuring the implant ourselves, because the clinic cannot be asked and no
   audiogram exists.

   Part 1 asks which narrowband bursts reach the aided ear AT THE LEVEL THE
   STUDY PRESENTS. That is a different question from a sound-booth audiogram
   and a more useful one: it measures the path every simulation travels —
   this ear, through this hearing aid, over this stream, at this volume.

   Part 2 is an interaural pitch match. A burst goes to the implant ear and a
   probe to the aided ear, and a staircase on the probe converges on the
   frequency the implant percept sits at. Note that no simulation is involved:
   the listener's own device does its own allocation, which is exactly what
   makes this a measurement of the real implant rather than of our model.

   Both parts are saved incrementally. Either one alone is useful, and a
   session that stops halfway still contributes. */

const MAP = {
  manifest: null,
  detectIx: 0, detect: [],
  matchIx: 0, match: [],
  st: null,            /* current staircase */
  playing: false,
};

/* Eighth-octave ladder steps: one octave, half, quarter, eighth.

   Simulated against synthetic listeners before deployment, which is the only
   reason the two settings below are what they are. The obvious choices were
   both wrong:

   - A quarter-octave ladder has a 3-semitone floor, enough to blur the very
     mismatch this exists to size.
   - Advancing the step every SECOND reversal and averaging the last four
     never reached the finest step at all, so early coarse reversals dominated
     the estimate. That left a 4.5-semitone dependence on which side the
     staircase started from — the answer was partly just the starting point.

   Advancing on every reversal and averaging only the reversals taken at the
   finest step costs about two extra trials and cuts the start-side dependence
   to 0.8 st and the median error to 0.5 st. */
const MAP_STEPS = [8, 4, 2, 1];
const MAP_TARGET_REVERSALS = 6;
const MAP_MAX_TRIALS = 18;

function mapNearestProbe(hz) {
  const p = MAP.manifest.probe;
  let best = 0, bestd = Infinity;
  for (let i = 0; i < p.length; i++) {
    const d = Math.abs(Math.log2(p[i].center_hz / hz));
    if (d < bestd) { bestd = d; best = i; }
  }
  return best;
}

async function startMapping() {
  audioCtx();
  /* Every mapping stimulus is deliberately in ONE channel, so a path that
     collapses to mono makes the whole measurement meaningless while still
     sounding entirely plausible — the detection screen would report bands as
     audible that reached the wrong ear, and the pitch match would compare a
     percept against itself. The channel check is the only thing standing
     between that and a wasted evening, so it is a gate rather than advice. */
  if (!S.channelsSeparate) {
    $('troubleTitle').textContent = 'The ears need checking first.';
    $('troubleNote').textContent =
      'These sounds go to one ear at a time, so they only mean something if ' +
      'the two sides are genuinely separate. That check takes a few seconds.';
    show('trouble');
    return;
  }
  try {
    const m = await api('/api/mapping');
    MAP.manifest = m.mapping;
    if (!MAP.manifest || !MAP.manifest.detect.length) {
      $('troubleTitle').textContent = 'The mapping stimuli are not installed.';
      $('troubleNote').textContent =
        'Run scripts/make_mapping_session.py into the audio directory.';
      show('trouble');
      return;
    }
  } catch {
    show('trouble');
    return;
  }
  /* Resume, rather than start over.
     This is expected to take several sittings, so anything already answered
     must not be asked again — repeating a tedious task is how a listener stops
     cooperating, and it happened here before with the balance staircase. */
  const prior = (await api('/api/mapping').catch(() => ({}))).result || {};
  MAP.detect = Array.isArray(prior.detect) ? prior.detect.slice() : [];
  MAP.match = Array.isArray(prior.match) ? prior.match.filter(m => m && m.resolved) : [];
  MAP.detectIx = MAP.detect.length;
  MAP.matchIx = MAP.match.length;

  const dTotal = MAP.manifest.detect.length;
  const mTotal = MAP.manifest.match.length;
  const doneAll = MAP.detectIx >= dTotal && MAP.matchIx >= mTotal;
  $('mapIntroNote').textContent = doneAll
    ? 'This is already finished. Going again replaces it with fresh answers.'
    : (MAP.detectIx || MAP.matchIx)
      ? `Picking up where you left off — ${MAP.detectIx} of ${dTotal} whispers `
        + `and ${MAP.matchIx} of ${mTotal} pairs already done.`
      : '';
  if (doneAll) { MAP.detect = []; MAP.match = []; MAP.detectIx = MAP.matchIx = 0; }
  show('mapintro');
}

/* ---- part 1: detection ---- */

function mapDetectShow() {
  const d = MAP.manifest.detect;
  if (MAP.detectIx >= d.length) { mapMatchBegin(); return; }
  $('mdCount').textContent = `Whisper ${MAP.detectIx + 1} of ${d.length}`;
  $('mdPlay').textContent = 'Play it';
  $('mdClear').disabled = $('mdFaint').disabled = $('mdNone').disabled = true;
  show('mapdetect');
}

$('mdPlay').addEventListener('click', async () => {
  if (MAP.playing) return;
  MAP.playing = true;
  $('mdPlay').disabled = true;
  const rec = MAP.manifest.detect[MAP.detectIx];
  try {
    const buf = await loadBuffer(rec.file);
    const acousticIsLeft = IMPLANT_EAR !== 'left';
    $(acousticIsLeft ? 'mdL' : 'mdR').classList.add('on');
    await playBuffer(buf);          /* no balance offset: one ear, by design */
    earsOff('mdL', 'mdR');
    $('mdClear').disabled = $('mdFaint').disabled = $('mdNone').disabled = false;
    $('mdPlay').textContent = 'Play again';
  } catch {
    show('trouble');
  } finally {
    MAP.playing = false;
    $('mdPlay').disabled = false;
  }
});

function mapDetectAnswer(verdict) {
  const rec = MAP.manifest.detect[MAP.detectIx];
  MAP.detect.push({ center_hz: rec.center_hz, file: rec.file, heard: verdict });
  MAP.detectIx += 1;
  mapSave();                        /* durable now, not at the end */
  mapDetectShow();
}
$('mdClear').addEventListener('click', () => mapDetectAnswer('clear'));
$('mdFaint').addEventListener('click', () => mapDetectAnswer('faint'));
$('mdNone').addEventListener('click', () => mapDetectAnswer('none'));

/* ---- part 2: interaural pitch match ---- */

function mapMatchBegin() {
  MAP.matchIx = 0;
  mapMatchNext();
}

function mapMatchNext() {
  const refs = MAP.manifest.match;
  if (MAP.matchIx >= refs.length) { mapFinish(); return; }
  const ref = refs[MAP.matchIx];
  /* Start a full octave away, alternating side between references so the
     first probe is not always below — a fixed starting side anchors the
     answer toward it. */
  const from_below = MAP.matchIx % 2 === 0;
  const start = Math.max(0, Math.min(MAP.manifest.probe.length - 1,
    mapNearestProbe(ref.center_hz) + (from_below ? -MAP_STEPS[0] : MAP_STEPS[0])));
  MAP.st = {
    ref, i: start, stepIx: 0, dir: null,
    reversals: [], trials: 0, from_below, responses: [],
  };
  $('mmCount').textContent = `Pair ${MAP.matchIx + 1} of ${refs.length}`;
  $('mmPlay').textContent = 'Play both';
  mapMatchButtons(true);
  show('mapmatch');
}

function mapMatchButtons(disabled) {
  $('mmFirst').disabled = $('mmSecond').disabled = $('mmUnsure').disabled = disabled;
}

$('mmPlay').addEventListener('click', async () => {
  if (MAP.playing) return;
  MAP.playing = true;
  $('mmPlay').disabled = true;
  const st = MAP.st;
  const probe = MAP.manifest.probe[st.i];
  try {
    const [a, b] = await Promise.all([loadBuffer(st.ref.file), loadBuffer(probe.file)]);
    const implantIsRight = IMPLANT_EAR === 'right';
    $(implantIsRight ? 'mmR' : 'mmL').classList.add('on');
    await playBuffer(a);
    earsOff('mmL', 'mmR');
    await new Promise(r => setTimeout(r, 420));
    $(implantIsRight ? 'mmL' : 'mmR').classList.add('on');
    await playBuffer(b);
    earsOff('mmL', 'mmR');
    mapMatchButtons(false);
    $('mmPlay').textContent = 'Play again';
  } catch {
    show('trouble');
  } finally {
    MAP.playing = false;
    $('mmPlay').disabled = false;
  }
});

/* `higher` is which interval sounded higher: 'first' = the implant, 'second'
   = the probe. If the probe sounded higher the ladder steps down, and the
   other way round. */
function mapMatchAnswer(higher) {
  const st = MAP.st;
  const probe = MAP.manifest.probe[st.i];
  st.trials += 1;
  st.responses.push({ probe_hz: probe.center_hz, higher });

  if (higher === 'unsure') {
    /* Not a direction, so it cannot move the ladder. Recorded because a run
       of them means the two percepts are not comparable at this frequency,
       which is itself a finding. */
    if (st.trials >= MAP_MAX_TRIALS) { mapMatchDone(); return; }
    mapMatchButtons(true);
    $('mmPlay').textContent = 'Play both';
    return;
  }

  const probeHigher = higher === 'second';
  const newDir = probeHigher ? 'down' : 'up';
  if (st.dir !== null && newDir !== st.dir) {
    /* Step size is recorded with the reversal, because only the reversals
       taken at the finest step carry the resolution this method claims. */
    st.reversals.push({ hz: probe.center_hz, stepIx: st.stepIx });
    if (st.stepIx < MAP_STEPS.length - 1) st.stepIx += 1;
  }
  st.dir = newDir;
  st.i += probeHigher ? -MAP_STEPS[st.stepIx] : MAP_STEPS[st.stepIx];
  const last = MAP.manifest.probe.length - 1;
  const pinned = st.i < 0 || st.i > last;
  st.i = Math.max(0, Math.min(last, st.i));

  if (st.reversals.length >= MAP_TARGET_REVERSALS || st.trials >= MAP_MAX_TRIALS
      || (pinned && st.trials > 6 && st.reversals.length === 0)) {
    mapMatchDone();
    return;
  }
  mapMatchButtons(true);
  $('mmPlay').textContent = 'Play both';
}
$('mmFirst').addEventListener('click', () => mapMatchAnswer('first'));
$('mmSecond').addEventListener('click', () => mapMatchAnswer('second'));
$('mmUnsure').addEventListener('click', () => mapMatchAnswer('unsure'));

function mapMatchDone() {
  const st = MAP.st;
  /* Average only the reversals taken at the finest step; fall back to the
     last four if the staircase never got that far, which is a coarser answer
     and is flagged as such by `resolved` below.

     Geometric mean, because pitch is logarithmic — averaging in Hz would bias
     every estimate upward. */
  const finest = st.reversals.filter(r => r.stepIx === MAP_STEPS.length - 1);
  const use = (finest.length >= 2 ? finest : st.reversals).slice(-4);
  const est = use.length
    ? Math.pow(2, use.reduce((a, r) => a + Math.log2(r.hz), 0) / use.length)
    : null;
  MAP.match.push({
    ci_hz: st.ref.center_hz,
    file: st.ref.file,
    match_hz: est === null ? null : Math.round(est * 10) / 10,
    shift_semitones: est === null ? null
      : Math.round(1200 * Math.log2(est / st.ref.center_hz)) / 100,
    reversals: st.reversals,
    n_trials: st.trials,
    started_below: st.from_below,
    /* Resolved means it reached the finest step and reversed there at least
       twice. Anything less is a coarse estimate and must not be read as a
       measurement at this method's stated resolution. */
    resolved: est !== null && finest.length >= 2,
    at_finest_step: finest.length,
    responses: st.responses,
  });
  MAP.matchIx += 1;
  mapSave();                        /* each reference saved as it completes */
  mapMatchNext();
}

async function mapSave() {
  try {
    await api('/api/mapping', {
      detect: MAP.detect,
      match: MAP.match,
      complete: MAP.detectIx >= MAP.manifest.detect.length
                && MAP.matchIx >= MAP.manifest.match.length,
    });
  } catch { /* a failed write must never interrupt a listener */ }
}

function mapFinish() {
  mapSave();
  const heard = MAP.detect.filter(d => d.heard !== 'none').length;
  const resolved = MAP.match.filter(m => m.resolved).length;
  $('doneNote').textContent =
    `${heard} of ${MAP.detect.length} whispers reached the aided ear` +
    (resolved ? `, and ${resolved} pitch match${resolved === 1 ? '' : 'es'} settled.` : '.');
  show('done');
}

$('mapBtn').addEventListener('click', startMapping);
$('mapGo').addEventListener('click', () => mapDetectShow());
$('mapBack').addEventListener('click', () => begin());

if ('serviceWorker' in navigator && location.protocol === 'https:') {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
