# DansProxy

A simple web proxy built on [Scramjet](https://github.com/MercuryWorkshop/scramjet). Enter a URL or
search terms, and the page loads through the proxy — including JavaScript-heavy sites like YouTube.

## Run

Requires Node.js 20+.

```sh
npm install
npm start
```

Open http://localhost:8080. `PORT` can be set (default `8080`).

## Deploy to Render

Web service settings: **Language** Node, **Build Command** `npm install`, **Start Command** `npm start`,
**Instance Type** Free. (`render.yaml` has the same settings for Blueprint deploys.)

## How it works

- `public/` — the homepage and viewer. A service worker (`sw.js`) intercepts every request the
  proxied page makes and rewrites it through Scramjet.
- `src/index.js` — serves the UI and Scramjet files, and runs a Wisp server at `/wisp/` that the
  browser tunnels its traffic through. Local/private network addresses are blocked, and DNS goes
  through Cloudflare's family filter (1.1.1.3).

## Limitations

- Needs HTTPS (or localhost) because it relies on a service worker.
- DRM streaming services (Netflix, Disney+, etc.) don't work.
- All traffic, including video, counts against the host's bandwidth.

Licensed under AGPL-3.0, following Scramjet.
