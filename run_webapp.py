"""
run_webapp.py -- start AlphaGuard AI (the research terminal) with one command.

    python run_webapp.py            # build the UI if needed, then serve UI + API on http://127.0.0.1:8000
    python run_webapp.py --open     # same, and open it in your browser
    python run_webapp.py --dev      # two processes with hot reload: API :8000, UI :5173 (for editing the UI)
    python run_webapp.py --rebuild  # force a fresh UI build first

What it does NOT do, on purpose: it never runs a strategy. Results come from
`python -m webapp.backend.snapshot`, a separate step you run from the terminal
(that is where the harness discipline applies). This script only SERVES what
that step already wrote, so starting the app is always fast and always safe.

How the pieces fit (see README, "Web app v2"):
    snapshot command --writes--> webapp/snapshots/*.json --read by--> API --called by--> browser UI
In the default mode the API process also serves the built UI files, so one
Python process, one port, nothing else to start and no Node needed at runtime
(Node is only used to BUILD the UI). In --dev mode Vite serves the UI with hot
reload and forwards /api/* to the API.

Standard library only; binds to 127.0.0.1 so the app is reachable from this
computer only.
"""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(ROOT, "webapp", "frontend")
DIST_INDEX = os.path.join(FRONTEND, "dist", "index.html")
MANIFEST = os.path.join(ROOT, "webapp", "snapshots", "manifest.json")
HOST = "127.0.0.1"
API_PORT = 8000
VITE_PORT = 5173


def say(msg: str) -> None:
    print(f"[webapp] {msg}", flush=True)


def port_is_free(port: int) -> bool:
    """True if nothing is listening on the port, on IPv4 or IPv6 (some tools bind only ::1)."""
    for family, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex((addr, port)) == 0:
                    return False
        except OSError:
            continue                                     # that address family is unavailable here
    return True


def require_port(port: int, what: str) -> None:
    if not port_is_free(port):
        say(f"Port {port} ({what}) is already in use -- probably an earlier run of this app, or another program.")
        say(f"Close that one, or choose another port with --port (default mode). Find the owner with: netstat -ano | findstr :{port}")
        sys.exit(1)


def newest_mtime(paths) -> float:
    newest = 0.0
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in ("node_modules", "dist")]
                for f in files:
                    newest = max(newest, os.path.getmtime(os.path.join(root, f)))
        elif os.path.exists(p):
            newest = max(newest, os.path.getmtime(p))
    return newest


def ui_needs_build() -> bool:
    if not os.path.exists(DIST_INDEX):
        return True
    sources = [os.path.join(FRONTEND, "src"), os.path.join(FRONTEND, "index.html"),
               os.path.join(FRONTEND, "package.json"), os.path.join(FRONTEND, "vite.config.ts")]
    return newest_mtime(sources) > os.path.getmtime(DIST_INDEX)


def run_npm(npm: str, *args: str) -> None:
    say("npm " + " ".join(args))
    result = subprocess.run([npm, *args], cwd=FRONTEND)
    if result.returncode != 0:
        say(f"`npm {' '.join(args)}` failed (exit {result.returncode}). The messages above say why.")
        sys.exit(result.returncode)


def ensure_ui_built(force: bool) -> None:
    npm = shutil.which("npm")
    if not force and not ui_needs_build():
        say("UI build is up to date.")
        return
    if npm is None:
        if os.path.exists(DIST_INDEX):
            say("WARNING: npm (Node.js) was not found, so the UI cannot be rebuilt; serving the existing build.")
            return
        say("The UI has not been built and npm (Node.js) was not found. Install Node.js 22+ from nodejs.org, "
            "then run this again.")
        sys.exit(1)
    if not os.path.isdir(os.path.join(FRONTEND, "node_modules")):
        say("First run: installing the UI's dependencies (needs internet, one time only)...")
        run_npm(npm, "install")
    say("Building the UI...")
    run_npm(npm, "run", "build")


def check_python_packages() -> None:
    try:
        import fastapi, uvicorn  # noqa: F401
    except ImportError as e:
        say(f"Missing package: {e.name}. Run with the Python that has the project's packages installed "
            f"(pip install -r requirements.txt). This Python is: {sys.executable}")
        sys.exit(1)


def check_snapshot() -> None:
    if os.path.exists(MANIFEST):
        return
    say("WARNING: no results snapshot found (webapp/snapshots/manifest.json). The app will start, but pages will "
        "show an error until you generate one. It takes roughly 20 minutes and is run separately on purpose:")
    say("    python -m webapp.backend.snapshot")
    say("    (or one strategy, ~1 minute:  python -m webapp.backend.snapshot --only ma_crossover_nifty50)")


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop a child AND everything it started (npm launches node, which launches vite)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()


def open_when_up(url: str, port: int) -> None:
    for _ in range(100):
        if not port_is_free(port):
            webbrowser.open(url)
            return
        time.sleep(0.2)


def main() -> int:
    ap = argparse.ArgumentParser(description="Start AlphaGuard AI, the research terminal (read-only; never runs a strategy).")
    ap.add_argument("--dev", action="store_true", help="API on :8000 plus the Vite dev server on :5173 (hot reload)")
    ap.add_argument("--rebuild", action="store_true", help="force a fresh UI build")
    ap.add_argument("--no-build", action="store_true", help="never build; serve whatever is in webapp/frontend/dist")
    ap.add_argument("--open", action="store_true", help="open the app in your browser once it is up")
    ap.add_argument("--port", type=int, default=API_PORT, help=f"port for the default mode (default {API_PORT})")
    args = ap.parse_args()

    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    check_python_packages()
    check_snapshot()

    import uvicorn

    if args.dev:
        npm = shutil.which("npm")
        if npm is None:
            say("--dev needs npm (Node.js), which was not found.")
            return 1
        if not os.path.isdir(os.path.join(FRONTEND, "node_modules")):
            run_npm(npm, "install")
        require_port(API_PORT, "API")
        require_port(VITE_PORT, "UI dev server")
        url = f"http://{HOST}:{VITE_PORT}"
        say(f"DEV MODE. UI {url}  (hot reload)   API http://{HOST}:{API_PORT}/docs")
        vite = subprocess.Popen([npm, "run", "dev"], cwd=FRONTEND)
        if args.open:
            threading.Thread(target=open_when_up, args=(url, VITE_PORT), daemon=True).start()
        try:
            uvicorn.run("webapp.backend.main:app", host=HOST, port=API_PORT, log_level="info")
        finally:
            kill_tree(vite)
        return 0

    if not args.no_build:
        ensure_ui_built(args.rebuild)
    elif not os.path.exists(DIST_INDEX):
        say("--no-build was given but there is no UI build. Run without --no-build once.")
        return 1
    require_port(args.port, "app")
    url = f"http://{HOST}:{args.port}"
    say(f"Serving AlphaGuard AI at {url}   (API docs: {url}/docs)   Ctrl+C to stop.")
    if args.open:
        threading.Thread(target=open_when_up, args=(url, args.port), daemon=True).start()
    uvicorn.run("webapp.backend.main:app", host=HOST, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("Stopped.")
        sys.exit(0)
