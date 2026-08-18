"""Create the CAIRN GitHub App through GitHub's manifest flow.

**Why this exists rather than a checklist.** Creating the App by hand means
setting four permissions, four event subscriptions, a webhook URL and a secret
across two screens, and every one of them is a place to be wrong in a way that
looks like "no events arrive". The manifest flow lets GitHub build the App from
a declaration this repository holds, so the permissions that end up on the App
are the permissions in version control.

It also means the credentials never pass through a human. GitHub generates the
webhook secret and the private key and hands them back once, to this process,
which writes them straight to `.env` — nothing is copied out of a browser, and
nothing lands in a terminal history or a chat message.

**Read-only, and structurally so.** The permissions below are the complete set
`cairn_api` uses, all `read`. Widening one to make something work would break a
product invariant, so they are declared here and asserted in the test suite
rather than left to whoever clicks through the form.

Usage:

    python scripts/create_github_app.py --webhook-url https://smee.io/<channel>

Open the URL it prints, press GitHub's "Create GitHub App" button, and the
credentials appear in `.env`. Nothing else to copy.
"""

from __future__ import annotations

import argparse
import http.server
import json
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

#: Where GitHub sends the browser back to, and therefore what this serves.
CALLBACK_PORT = 8765
CALLBACK_HOST = "localhost"

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env"

#: Exactly what `cairn_api` reads, and nothing else.
#:
#: - contents: `github/client.py`'s GraphQL commit history, for backfill.
#: - pull_requests / issues: what `pipeline/jobs.py::_read_evidence` turns into
#:   evidence a fact can cite.
#: - metadata: mandatory, granted to every App.
#:
#: No write permission of any kind. No account or organisation permissions:
#: nothing in the codebase calls an endpoint that needs one.
PERMISSIONS = {
    "contents": "read",
    "pull_requests": "read",
    "issues": "read",
    "metadata": "read",
}

#: `push` is the only one that carries commits, and therefore the only one that
#: produces an attributed fact today. The other three become evidence a fact can
#: cite. Installation events are delivered without being subscribed to.
EVENTS = ["push", "pull_request", "issues", "issue_comment"]


def manifest(*, name: str, webhook_url: str, app_url: str) -> dict[str, object]:
    """The App, as a declaration GitHub builds from."""
    return {
        "name": name,
        "url": app_url,
        "hook_attributes": {"url": webhook_url, "active": True},
        "redirect_url": f"http://{CALLBACK_HOST}:{CALLBACK_PORT}/callback",
        # Private: installable only on the account that owns it. Widening this
        # is a decision about who may install CAIRN, not a convenience.
        "public": False,
        "default_permissions": PERMISSIONS,
        "default_events": EVENTS,
    }


_FORM = """<!doctype html>
<title>Create the CAIRN GitHub App</title>
<style>
  body {{ font: 16px/1.6 system-ui, sans-serif; max-width: 34rem; margin: 4rem auto; padding: 0 1rem; }}
  button {{ font: inherit; padding: .7rem 1.2rem; cursor: pointer; }}
  code {{ background: #f4f4f4; padding: .1rem .3rem; }}
</style>
<h1>Create the CAIRN GitHub App</h1>
<p>This posts a manifest to GitHub. You will see the permissions it asks for
   &mdash; all <strong>read-only</strong> &mdash; before anything is created.</p>
<form action="https://github.com/settings/apps/new?state={state}" method="post">
  <input type="hidden" name="manifest" value='{manifest}'>
  <button type="submit">Continue to GitHub</button>
</form>
"""

_DONE = """<!doctype html>
<title>App created</title>
<style>body {{ font: 16px/1.6 system-ui, sans-serif; max-width: 34rem; margin: 4rem auto; padding: 0 1rem; }}</style>
<h1>Created.</h1>
<p>App ID, private key and webhook secret were written to <code>.env</code>.
   Nothing was printed to a terminal.</p>
<p>Next: install it on one repository at <a href="{html_url}/installations/new">{html_url}/installations/new</a>,
   then return to the session.</p>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves the form, then receives GitHub's redirect."""

    state: str = ""
    payload: dict[str, object] = {}  # noqa: RUF012 - set on the class, read after serve

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._send(
                _FORM.format(
                    state=self.state,
                    # Single quotes wrap the attribute, so the JSON's double
                    # quotes need no escaping and the manifest stays readable.
                    manifest=json.dumps(self.server.manifest),  # type: ignore[attr-defined]
                )
            )
            return

        if parsed.path == "/callback":
            query = urllib.parse.parse_qs(parsed.query)
            code = (query.get("code") or [""])[0]
            returned_state = (query.get("state") or [""])[0]
            if not code:
                self._send("<h1>No code in the redirect.</h1>", status=400)
                return
            if not secrets.compare_digest(returned_state, self.state):
                # The state is why this cannot be driven by a link somebody
                # sends you: a mismatch means the redirect did not come from
                # the form this process served.
                self._send("<h1>State mismatch. Refusing.</h1>", status=400)
                return

            converted = _convert(code)
            _write_env(converted)
            _Handler.payload = converted
            self._send(_DONE.format(html_url=converted.get("html_url", "")))
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        self._send("<h1>Not here.</h1>", status=404)

    def _send(self, body: str, *, status: int = 200) -> None:
        encoded = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args: object) -> None:
        """Silent. The query string carries the one-time conversion code."""


def _convert(code: str) -> dict[str, object]:
    """Exchange the temporary code for the App's credentials.

    One shot: the code is single-use and the private key is returned exactly
    once. If this call fails after GitHub created the App, the App exists and
    its key does not — delete it and run this again rather than hunting for a
    way to re-read the key, because there is not one.
    """
    # S310: the scheme is a literal https here, not caller-controlled - only the
    # one-time code is interpolated, and it is percent-encoded.
    request = urllib.request.Request(
        f"https://api.github.com/app-manifests/{urllib.parse.quote(code)}/conversions",
        method="POST",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "cairn-setup"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        body: dict[str, object] = json.loads(response.read())
    return body


def _write_env(app: dict[str, object]) -> None:
    """Write the three variables, replacing any existing values in place.

    Never printed, never returned to the browser beyond the App's public URL.
    The PEM is stored with literal ``\\n`` escapes so it survives a single line
    of a dotenv file; `Settings` reads it back as a normal multi-line key.
    """
    pem = str(app.get("pem", ""))
    values = {
        "CAIRN_GITHUB_APP_ID": str(app.get("id", "")),
        "CAIRN_GITHUB_WEBHOOK_SECRET": str(app.get("webhook_secret", "")),
        "CAIRN_GITHUB_PRIVATE_KEY": pem.replace("\n", "\\n"),
    }

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    for key, value in values.items():
        replacement = f"{key}={value}"
        for index, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[index] = replacement
                break
        else:
            lines.append(replacement)

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--webhook-url",
        required=True,
        help="Where GitHub should deliver. A tunnel today; the staging URL later.",
    )
    parser.add_argument("--name", default="CAIRN (dev)")
    parser.add_argument("--app-url", default="https://github.com/waqasabid-del/Crain")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    _Handler.state = secrets.token_urlsafe(24)
    server = http.server.HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _Handler)
    server.manifest = manifest(  # type: ignore[attr-defined]
        name=args.name, webhook_url=args.webhook_url, app_url=args.app_url
    )

    url = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}/"
    print(f"Open {url} and press the button.")
    print(f"  webhook -> {args.webhook_url}")
    print(f"  permissions -> {', '.join(f'{k}:{v}' for k, v in PERMISSIONS.items())}")
    print(f"  events -> {', '.join(EVENTS)}")
    if not args.no_browser:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()

    server.serve_forever()

    if not _Handler.payload:
        print("No App was created.", file=sys.stderr)
        return 1

    print(f"Created: {_Handler.payload.get('html_url')}")
    print("App id, webhook secret and private key written to .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
