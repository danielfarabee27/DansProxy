# DansProxy

A minimal web proxy. Enter a URL, and the page is fetched by the server and shown in the browser.

No dependencies — just Python 3.8+.

## Run

```sh
python3 server.py
```

Open http://localhost:8080.

To use it from a phone or Chromebook on the same Wi‑Fi, listen on all interfaces and visit
`http://<this-computer's-IP>:8080`:

```sh
HOST=0.0.0.0 python3 server.py
```

`PORT` can also be set (default `8080`).

## Deploy to Render

`render.yaml` configures a free Render web service. Push this repo to GitHub, then in Render choose
**New → Blueprint**, pick the repo, and click **Apply**. The site will be at
`https://dansproxy.onrender.com` (or a similar name if taken).

## How it works

- `static/` — the homepage and viewer (URL bar + iframe).
- `server.py` — serves the UI and proxies pages at `/p/<url>`, e.g. `/p/https://example.com/`.
  HTML and CSS links are rewritten to go back through the proxy; redirects are followed hop by hop.
  Requests to local/private network addresses are blocked.

## Limitations

- Sites that build URLs heavily in JavaScript (big web apps, video sites) may partly break.
- Cookies aren't passed through, so logging into sites won't work.
