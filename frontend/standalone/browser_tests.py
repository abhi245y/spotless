#!/usr/bin/env python3
"""Run offline JS tests in an owned, temporary Firefox headless profile."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = Path(__file__).resolve().parent
ADAPTER = r"""
const queue = [];
window.__dirname = '/feature/standalone';
const sources = SOURCE_DATA;
function fail(message) { throw new Error(message); }
const assertions = {
  ok(value, message) { if (!value) fail(message || 'Expected truthy value'); },
  equal(actual, expected, message) {
    if (!Object.is(actual, expected)) fail((message || 'Equality failed') + ': ' + String(actual) + ' !== ' + String(expected));
  },
  async rejects(promise, expected) {
    try { await promise; } catch (error) {
      if (typeof expected === 'function' ? expected(error) : expected.test(String(error.message))) return;
      fail('Unexpected rejection: ' + error);
    }
    fail('Expected rejection');
  }
};
const evaluator = Function('context', 'code', 'with(context){ return eval(code); }');
window.require = function(name) {
  if (name === 'node:assert/strict') return assertions;
  if (name === 'node:fs') return {readFileSync(name) {
    const key = name.split('/').pop();
    if (!(key in sources)) fail('Unknown fixture: ' + key);
    return sources[key];
  }};
  if (name === 'node:path') return {join(...parts) { return parts.join('/'); }};
  if (name === 'node:vm') return {
    createContext(value) { return value; },
    runInContext(code, context) { return evaluator(context, code); },
    runInNewContext(code, context) { return evaluator(context, code); }
  };
  if (name === 'node:test') return {test(name, run) { queue.push({name, run}); }};
  fail('Unknown module: ' + name);
};
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    sources = {"spotifytv.js": (HERE.parent / "spotifytv.js").read_text(),
               "spotifytv.standalone.js": (HERE / "spotifytv.standalone.js").read_text(),
               "standalone-shim.js": (HERE / "standalone-shim.js").read_text()}
    adapter = ADAPTER.replace("SOURCE_DATA", json.dumps(sources))
    tests = (HERE / "test_patch.js").read_text()
    script = adapter + "\n" + tests + r"""
queue.push({name:'entire generated bundle parses without execution', run() {
  new Function(sources['spotifytv.standalone.js']);
}});
(async function() {
 const results = [];
 for (const entry of queue) {
  try { await entry.run(); results.push({name:entry.name,passed:true}); }
  catch(error) { results.push({name:entry.name,passed:false,error:String(error.stack || error)}); }
 }
 await fetch('/result', {method:'POST', headers:{'Content-Type':'application/json'},
   body:JSON.stringify({runtime:navigator.userAgent, results,
     passed:results.filter(x=>x.passed).length, failed:results.filter(x=>!x.passed).length})});
})();
"""
    completed = threading.Event()
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_GET(self):
            if self.path == "/":
                data = b'<!doctype html><meta charset="utf-8"><title>Isolated offline tests</title><script src="/tests.js"></script>'
                mime = "text/html"
            elif self.path == "/tests.js":
                data, mime = script.encode(), "application/javascript"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self' 'unsafe-eval'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/result":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 131072:
                self.send_error(413)
                return
            result.update(json.loads(self.rfile.read(length)))
            self.send_response(204)
            self.end_headers()
            completed.set()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory(prefix="firefox-profile-", dir=HERE) as profile:
        prefs = {
            "browser.shell.checkDefaultBrowser": False,
            "browser.startup.homepage_override.mstone": "ignore",
            "browser.startup.page": 0,
            "browser.newtabpage.enabled": False,
            "browser.aboutwelcome.enabled": False,
            "browser.safebrowsing.phishing.enabled": False,
            "browser.safebrowsing.malware.enabled": False,
            "network.prefetch-next": False,
            "network.dns.disablePrefetch": True,
            "network.captive-portal-service.enabled": False,
            "network.connectivity-service.enabled": False,
            "datareporting.healthreport.uploadEnabled": False,
            "datareporting.policy.dataSubmissionEnabled": False,
            "toolkit.telemetry.enabled": False,
            "app.update.auto": False,
            "extensions.update.enabled": False,
        }
        Path(profile, "user.js").write_text("\n".join(
            "user_pref(" + json.dumps(k) + ", " + json.dumps(v) + ");" for k, v in prefs.items()))
        with (HERE / "firefox-test.log").open("w") as log:
            process = subprocess.Popen(["firefox", "--headless", "--no-remote", "--profile", profile,
                f"http://127.0.0.1:{server.server_port}/"], stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, env={**os.environ, "MOZ_CRASHREPORTER_DISABLE": "1"})
            try:
                if not completed.wait(args.timeout):
                    raise RuntimeError("Offline Firefox test timed out")
            finally:
                # Own child process group only; never touches user's browser.
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                server.shutdown()
    (HERE / "browser-test-results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result.get("failed") else 0)


if __name__ == "__main__":
    main()
