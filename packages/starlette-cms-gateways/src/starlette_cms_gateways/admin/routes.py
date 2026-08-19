"""
Gateway admin shell routes — ``GET /shell`` and ``/static/*``.

Mirrors the structure of ``starlette_editor.routes`` — a single HTML shell page
with an inlined bootstrap config object and a small vanilla-JS frontend that
calls the gateway API routes registered on the CMS.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

if TYPE_CHECKING:
    from starlette_cms_gateways.admin.app import GatewayAdmin

STATIC_DIR = pathlib.Path(__file__).parent / "static"


def _js_string(value: str | None) -> str:
    """Safely encode a Python string value for inline JavaScript."""
    if value is None:
        return "null"
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return f'"{escaped}"'


def make_admin_routes(admin: GatewayAdmin) -> list:
    """
    Return the routes for the gateway admin sub-application.

    Routes:
      GET /shell     — HTML shell page (injects JS config, renders gateway UI)
      /static/*      — Static file serving (if ``static/`` directory exists)
    """

    async def shell_endpoint(request: Request) -> HTMLResponse:
        """Serve the gateway admin single-page shell."""
        if admin.auth is not None:
            allowed = admin.auth(request)
            if hasattr(allowed, "__await__"):
                allowed = await allowed
            if not allowed:
                # Redirect unauthenticated visitors to the login page, sending
                # them back to the shell (?next=) once they have signed in.
                return RedirectResponse(
                    f"{admin.login_path}?next={request.url.path}",
                    status_code=302,
                )

        mount = admin.mount_path.rstrip("/")
        cms_base = admin.cms.mount_path.rstrip("/")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Gateway Admin</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      background: #0f0f0f;
      color: #e0e0e0;
      padding: 2rem;
      line-height: 1.5;
    }}
    h1 {{ font-size: 1.5rem; font-weight: 600; margin-bottom: 1.5rem; color: #fff; }}
    h2 {{ font-size: 1.1rem; font-weight: 600; margin-bottom: 0.75rem; color: #ccc; }}
    #gateways {{ display: grid; gap: 1rem; }}
    .gateway-card {{
      background: #1a1a1a;
      border: 1px solid #2a2a2a;
      border-radius: 8px;
      padding: 1.25rem;
    }}
    .gateway-name {{
      font-size: 1rem;
      font-weight: 600;
      color: #7dd3fc;
      margin-bottom: 0.4rem;
    }}
    .gateway-meta {{
      font-size: 0.8rem;
      color: #888;
      margin-bottom: 0.5rem;
    }}
    .gateway-meta span {{ margin-right: 1rem; }}
    .last-synced {{ font-size: 0.78rem; color: #6b7280; margin-bottom: 0.75rem; }}
    .sync-btn {{
      background: #1d4ed8;
      color: #fff;
      border: none;
      border-radius: 5px;
      padding: 0.45rem 1rem;
      font-size: 0.85rem;
      cursor: pointer;
      transition: background 0.15s;
    }}
    .sync-btn:hover {{ background: #2563eb; }}
    .sync-btn:disabled {{ background: #374151; color: #6b7280; cursor: not-allowed; }}
    .job-status {{
      margin-top: 0.75rem;
      font-size: 0.82rem;
      min-height: 1.2em;
    }}
    .status-running {{ color: #fbbf24; }}
    .status-done {{ color: #34d399; }}
    .status-error {{ color: #f87171; }}
    .result-detail {{
      margin-top: 0.5rem;
      font-size: 0.78rem;
      color: #9ca3af;
      font-family: monospace;
    }}
    #loading {{ color: #888; }}
    #error-msg {{ color: #f87171; }}
  </style>
</head>
<body>
  <h1>Gateway Admin</h1>
  <div id="loading">Loading gateways…</div>
  <div id="error-msg" hidden></div>
  <div id="gateways" hidden></div>

  <script>
  (function () {{
    var CONFIG = {{
      cmsBase: {_js_string(cms_base)},
      apiKey: {_js_string(admin.cms.api_key)},
      mountPath: {_js_string(mount)}
    }};

    function authHeaders() {{
      return CONFIG.apiKey
        ? {{ "Authorization": "Bearer " + CONFIG.apiKey, "Content-Type": "application/json" }}
        : {{ "Content-Type": "application/json" }};
    }}

    async function apiFetch(path, opts) {{
      var resp = await fetch(CONFIG.cmsBase + path, Object.assign({{
        headers: authHeaders()
      }}, opts || {{}}));
      if (!resp.ok) throw new Error(resp.status + " " + resp.statusText);
      return resp.json();
    }}

    function renderMeta(gw) {{
      return [
        '<span>service: <b>' + esc(gw.service_name || '?') + '</b></span>',
        '<span>block: <b>' + esc(gw.block_type || '?') + '</b></span>',
        '<span>auto_publish: <b>' + gw.auto_publish + '</b></span>',
      ].join('');
    }}

    function esc(s) {{
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }}

    async function pollJob(gwName, runId, statusEl) {{
      var done = false;
      while (!done) {{
        await new Promise(function(r) {{ setTimeout(r, 1000); }});
        try {{
          var url = '/api/gateways/' + encodeURIComponent(gwName);
          url += '/sync/' + encodeURIComponent(runId);
          var job = await apiFetch(url);
          if (job.status === 'running') {{
            statusEl.textContent = '⏳ Running…';
            statusEl.className = 'job-status status-running';
          }} else if (job.status === 'done') {{
            var r = job.result || {{}};
            statusEl.className = 'job-status status-done';
            statusEl.innerHTML =
              '✓ Done &nbsp;' +
              '<span class="result-detail">' +
              'created=' + r.created + '  updated=' + r.updated +
              '  skipped=' + r.skipped + '  errors=' + (r.errors ? r.errors.length : 0) +
              '</span>';
            // Update last-synced display live without a page reload
            var lsEl = document.getElementById('lastsynced-' + CSS.escape(gwName));
            if (lsEl) {{ lsEl.innerHTML = 'Last synced: ' + esc(new Date().toISOString()); }}
            done = true;
          }} else {{
            statusEl.className = 'job-status status-error';
            statusEl.textContent = '✗ Error: ' + esc(job.error || 'unknown');
            done = true;
          }}
        }} catch (e) {{
          statusEl.className = 'job-status status-error';
          statusEl.textContent = '✗ Poll failed: ' + esc(e.message);
          done = true;
        }}
      }}
    }}

    function buildCard(gw) {{
      var lastSyncedVal = gw.last_synced
        ? esc(gw.last_synced)
        : '<em>Never</em>';
      var card = document.createElement('div');
      card.className = 'gateway-card';
      card.innerHTML =
        '<div class="gateway-name">' + esc(gw.name) + '</div>' +
        '<div class="gateway-meta">' + renderMeta(gw) + '</div>' +
        '<div class="last-synced" id="lastsynced-' + esc(gw.name) + '">Last synced: '  # noqa: E501
        + lastSyncedVal + '</div>' +
        // TODO: relative time ("2 hours ago") — future enhancement
        '<button class="sync-btn" id="btn-' + esc(gw.name) + '">▶ Sync now</button>' +
        '<div class="job-status" id="status-' + esc(gw.name) + '"></div>';

      var btn = card.querySelector('#btn-' + CSS.escape(gw.name));
      var statusEl = card.querySelector('#status-' + CSS.escape(gw.name));

      btn.addEventListener('click', async function () {{
        btn.disabled = true;
        statusEl.textContent = '⏳ Starting…';
        statusEl.className = 'job-status status-running';
        try {{
          var resp = await apiFetch('/api/gateways/' + encodeURIComponent(gw.name) + '/sync', {{
            method: 'POST'
          }});
          await pollJob(gw.name, resp.run_id, statusEl);
        }} catch (e) {{
          statusEl.className = 'job-status status-error';
          statusEl.textContent = '✗ ' + esc(e.message);
        }} finally {{
          btn.disabled = false;
        }}
      }});

      return card;
    }}

    async function init() {{
      var loadingEl = document.getElementById('loading');
      var errorEl = document.getElementById('error-msg');
      var gwEl = document.getElementById('gateways');

      try {{
        var data = await apiFetch('/api/gateways');
        loadingEl.hidden = true;

        if (!data.gateways || data.gateways.length === 0) {{
          gwEl.hidden = false;
          var epHint = '"starlette_cms_gateways.gateways"';
          gwEl.innerHTML =
            '<p style="color:#888">No gateways installed. ' +
            'Register one via <code>project.entry-points.' + epHint + '</code>.</p>';
          return;
        }}

        gwEl.hidden = false;
        data.gateways.forEach(function (gw) {{
          gwEl.appendChild(buildCard(gw));
        }});
      }} catch (e) {{
        loadingEl.hidden = true;
        errorEl.hidden = false;
        errorEl.textContent = 'Failed to load gateways: ' + e.message;
      }}
    }}

    init();
  }})();
  </script>
</body>
</html>"""
        return HTMLResponse(html)

    routes: list = [
        Route("/shell", endpoint=shell_endpoint, methods=["GET"]),
    ]

    if STATIC_DIR.exists():
        routes.append(Mount("/static", app=StaticFiles(directory=str(STATIC_DIR))))

    return routes
