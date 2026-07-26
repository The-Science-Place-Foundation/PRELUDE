# Listening companion — PWA

A home-network web app for collecting perceptual judgements. Installs to the
iPhone home screen from Safari; no App Store, no developer mode, no signing,
nothing that expires.

## Where it runs

`http://192.168.1.210:8080` — a container on the `BlackMesa-VLAN` ipvlan
network, so it holds a real LAN address without publishing a port on the host
or touching the router. **Not reachable from the internet, and deliberately has
no authentication.** A single listener on a home network, and a login screen on
something opened while tired at the end of a day would cost more than it
protects.

## Deploy

```bash
rsync -az --exclude data/ pwa/ user@server:~/PRELUDE/pwa/
rsync -az calibration/*.wav user@server:~/PRELUDE/pwa/data/audio/
ssh user@server 'cd ~/PRELUDE/pwa && docker compose up -d --build'
```

`data/audio` is mounted read-only; `data/sessions` receives the records. Both
sit beside the compose file on the host and are gitignored — session records are
health information and must not reach the public repository.

## Install on the phone

Safari → Share → **Add to Home Screen**. It launches full-screen with its own
icon.

## Two things worth knowing

**Service workers need HTTPS.** Over plain HTTP the app installs and runs, but
`sw.js` will not register, so there is no offline cache. On a home LAN with the
server always up that costs milliseconds, not capability. `mkcert` plus a
trusted CA profile on the phone would enable it if offline use is ever wanted.

**The phone is not the record.** Safari caps script-writable storage and can
evict it after a period of disuse, which would silently lose weeks of
judgements. Every response posts to the server as it happens;
`localStorage` keeps a local copy only as a safety net.

## Why the fitter runs server-side

The adaptive fitting logic is written and tested in Python. Reimplementing it in
JavaScript would mean maintaining two versions of the one component whose
correctness decides whether the collected judgements mean anything. The page
presents trials and reports choices; the server decides what to ask next.

## Endpoints

| Route | Purpose |
|---|---|
| `GET /health` | liveness, stimulus count, sessions on disk |
| `GET /api/session` | begin a session, returns the first trial |
| `POST /api/respond` | record a choice, returns the next trial |
| `POST /api/finish` | write the session record to disk |
| `GET /audio/<name>` | a stimulus; filenames validated, traversal rejected |
