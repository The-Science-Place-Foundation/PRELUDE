/* PRELUDE listening companion.
   Copyright (C) The Science Place Foundation and the PRELUDE contributors.
   Licensed under the GNU Affero General Public License v3.0 or later.

   Web Audio, not <audio> elements, for two reasons that both matter here:

   1. On iOS an <audio> element is silenced by the physical ringer switch.
      A session that plays nothing, with no visible cause, is a baffling
      failure mode for a listener to hit alone.
   2. Alternating presentation needs sample-accurate scheduling. A ragged
      segment boundary is audible as a click, and a click is both unpleasant
      and an unintended cue about which ear is active.

   Stereo channels are preserved end to end: the file's left channel reaches
   the left device and the right reaches the right. Nothing here mixes to mono,
   because the whole comparison depends on the ears staying separate. */

const S = {
  sessionId: null, trial: null, maxTrials: 40,
  shownAt: 0, playing: false, buffers: new Map(), ctx: null,
  answered: 0, sameCount: 0,
};

const $ = (id) => document.getElementById(id);
const views = [...document.querySelectorAll('.view')];

function show(name) {
  views.forEach(v => v.classList.toggle('hidden', v.dataset.view !== name));
}

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

/** Play one stimulus, returning a promise that settles when it ends. */
function playBuffer(buf) {
  return new Promise((resolve) => {
    const ctx = audioCtx();
    const src = ctx.createBufferSource();
    src.buffer = buf;
    // Straight to destination: no gain staging, no panning, no channel
    // merging. Levels were matched when the file was rendered, and anything
    // applied here would silently undo that.
    src.connect(ctx.destination);
    src.onended = resolve;
    src.start();
  });
}

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
      $('dotL').classList.add('on');
      $('dotR').classList.add('on');
      await playBuffer(bufs[k]);
      cards[k].classList.remove('sounding');
      $('dotL').classList.remove('on');
      $('dotR').classList.remove('on');
      if (k === 0) await new Promise(r => setTimeout(r, 420));
    }
    $('trialFoot').textContent = 'Choose whichever felt closer';
  } catch (err) {
    $('troubleNote').textContent =
      'That sound could not be loaded. The library may be unreachable.';
    show('trouble');
  } finally {
    S.playing = false;
    $('listenBtn').disabled = false;
    $('listenBtn').textContent = 'Listen again';
    $('cardA').disabled = $('cardB').disabled = false;
  }
}

/* ------------------------------------------------------------------ moon */

function paintMoon(done, total) {
  const frac = Math.max(0, Math.min(1, total ? done / total : 0));
  // A crescent that fills left to right. Deliberately not a percentage.
  $('moonFill').style.clipPath = `inset(0 ${(1 - frac) * 100}% 0 0)`;
  const names = ['The new moon', 'The thin crescent', 'The waxing half',
                 'The gibbous', 'The full moon'];
  $('moonName').textContent = names[Math.min(4, Math.floor(frac * 4.999))];
}

/* --------------------------------------------------------------- session */

async function api(path, body) {
  const res = await fetch(path, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  } : {});
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

async function begin() {
  audioCtx(); // unlock on this gesture, before any await
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
    startSettle();
  } catch {
    show('trouble');
  }
}

// Loudness perception drifts briefly after a device is reinserted, so a
// judgement made inside this window measures the adaptation rather than the
// sound. Enforced, not suggested.
function startSettle() {
  show('ritual');
  let t = 30;
  const btn = $('settleBtn'), note = $('settleNote');
  btn.disabled = true;
  const tick = setInterval(() => {
    t--;
    note.textContent = `Settling · 0:${String(Math.max(0, t)).padStart(2, '0')}`;
    if (t <= 0) {
      clearInterval(tick);
      note.textContent = 'Ready when you are';
      btn.disabled = false;
    }
  }, 1000);
}

function enterTrial() {
  show('trial');
  S.shownAt = performance.now();
  $('listenBtn').textContent = 'Listen';
  $('trialFoot').textContent = ' ';
  $('cardA').disabled = $('cardB').disabled = false;
}

async function respond(choice) {
  if (S.playing || !S.trial) return;
  const ms = Math.round(performance.now() - S.shownAt);
  if (choice === 'same') S.sameCount++;
  S.answered++;
  const payload = {
    session_id: S.sessionId, trial_id: S.trial.trial_id,
    chose: choice, response_ms: ms,
  };
  stash(payload); // local safety net; the server is the record

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
    await api('/api/finish', {
      session_id: S.sessionId, ended_early: early,
    });
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
  } catch { /* storage full or blocked; not worth interrupting a session */ }
}

/* ------------------------------------------------------------------ wire */

$('beginBtn').addEventListener('click', begin);
$('laterBtn').addEventListener('click', () => finish(true));
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
    const h = await api('/health');
    $('moonNote').textContent = h.stimuli
      ? `${h.sessions_on_disk} listening${h.sessions_on_disk === 1 ? '' : 's'} gathered so far. The shape of it is starting to show.`
      : 'The library is empty just now.';
    paintMoon(Math.min(h.sessions_on_disk, 12), 12);
    $('lenNote').textContent = 'Ten minutes';
  } catch {
    show('trouble');
  }
})();

if ('serviceWorker' in navigator && location.protocol === 'https:') {
  // Only over HTTPS: Safari requires a secure context, and registering over
  // plain HTTP fails noisily for no benefit.
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
