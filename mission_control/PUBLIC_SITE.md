# Temporary public dashboard

The dashboard needs its Python coordinator and local hardware feeds. A static GitHub Pages upload cannot run those services.

The public share uses a Cloudflare Quick Tunnel to a loopback proxy. `tools/share_site.py` forwards requests to the existing coordinator, retains operator authentication and same-origin checks, serves the favicon and current system explanation page, and compresses text/JSON responses. It exposes only HTTP routes, never the checkout or credential files.

Start the share while the coordinator is running on port 8092:

```sh
.venv/bin/python tools/share_site.py --upstream-port 8092 --port 8095 --finite-events
cloudflared tunnel --url http://127.0.0.1:8095 --no-autoupdate
```

Cloudflare prints the public HTTPS address. The Mac, coordinator, proxy, and tunnel must remain running. Restarting the tunnel produces a new address. Live views and operator commands use the existing operator token; the mission animation and decision exercises are public.

Cloudflare Quick Tunnels do not support persistent SSE. With `--finite-events`, the proxy returns one complete simulator event and a 1-second EventSource retry interval. The browser reconnects to receive the next snapshot. This keeps the simulator usable through the buffering tunnel; the direct local dashboard retains its continuous stream.

For the share launched from this chat, the current URL, process IDs, logs, and verification screenshot are in `~/.codex/state/team15/public-site/`. A `caffeinate` process prevents idle sleep while the tunnel is running. Stop the PIDs in `tunnel.pid` and `proxy.pid` to end the share; the sleep assertion ends when the tunnel exits. Tokens remain in the existing private credential file and are not embedded in source or public URLs.

The phone logo is used in `static/favicon.png`, `static/favicon.ico`, and `static/apple-touch-icon.png`. All dashboard pages link to these icons. The standalone fleet dashboard uses the same mark under its existing Leaflet asset route.

Validation: 26 mission-control/workspace unit tests passed; public HTTPS checks verified pages, favicon bytes, authenticated state/BLE/tracks/vision responses, unauthenticated command rejection, same-origin command validation, and a complete finite simulator event. Browser inspection verified that the mission animation and decision exercise load and the public document references the new favicon.

Reference: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
