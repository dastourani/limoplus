import os
import subprocess
import sys

os.environ.setdefault("MALLOC_ARENA_MAX", "2")

wsgi_app = "config.wsgi:application"
bind = "0.0.0.0:8000"  # the port set for the app in the ParsPack panel
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
# Threads: a slow phone downloading the APK, or a large upload, does not hold up everyone else.
worker_class = "gthread"
threads = int(os.environ.get("WEB_THREADS", "8"))
timeout = 120
accesslog = "-"
errorlog = "-"

HERE = os.path.dirname(os.path.abspath(__file__))
_jobs = None


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _nightly_enabled() -> bool:
    return _env_flag("NIGHTLY_JOBS")


def _staticfiles_fresh(base_dir: str | None = None) -> bool:
    """True when `staticfiles/staticfiles.json` already exists and is newer than app static sources and `requirements.txt`.
    Avoids spawning an extra Django + WhiteNoise compression process on every start when build already collected them."""
    base = base_dir or HERE
    manifest = os.path.join(base, "staticfiles", "staticfiles.json")
    try:
        manifest_mtime = os.path.getmtime(manifest)
        req = os.path.join(base, "requirements.txt")
        if os.path.isfile(req) and os.path.getmtime(req) > manifest_mtime:
            return False
        apps_dir = os.path.join(base, "apps")
        if os.path.isdir(apps_dir):
            for entry in os.scandir(apps_dir):
                if not entry.is_dir():
                    continue
                static_dir = os.path.join(entry.path, "static")
                if not os.path.isdir(static_dir):
                    continue
                for root, _, files in os.walk(static_dir):
                    for name in files:
                        if os.path.getmtime(os.path.join(root, name)) > manifest_mtime:
                            return False
        return True
    except OSError:
        return False


def on_starting(server):
    """Before serving, every start: bring the database up to date and gather the static files (panel, website)
    unless already collected during build. Skip entirely when `app.sh` already ran both steps."""
    if _env_flag("_LIMO_STARTUP_DONE"):
        return
    steps = []
    if not _env_flag("DISABLE_MIGRATE"):
        steps.append(["migrate", "--noinput"])
    if not _env_flag("DISABLE_COLLECTSTATIC") and not _staticfiles_fresh():
        steps.append(["collectstatic", "--noinput", "-v0"])
    for step in steps:
        done = subprocess.run([sys.executable, "manage.py", *step], cwd=HERE, check=False)
        if done.returncode:
            print(f"startup step failed: manage.py {' '.join(step)} (exit {done.returncode})", file=sys.stderr, flush=True)
            raise SystemExit(done.returncode)


def when_ready(server):
    """On multi-worker servers with NIGHTLY_JOBS=True: one separate process so jobs run only once.
    Single-worker deployments run the same loop in a daemon thread inside the worker (`post_worker_init`) to save RAM."""
    global _jobs
    if _nightly_enabled() and workers > 1:
        _jobs = subprocess.Popen([sys.executable, "manage.py", "nightly", "--loop"], cwd=HERE)


def post_worker_init(worker):
    """On single-worker servers (e.g. 256 MB PaaS): run hourly jobs in a daemon thread instead of a third Python process."""
    if _nightly_enabled() and workers == 1:
        from apps.catalog.management.commands.nightly import start_nightly_thread

        start_nightly_thread()


def on_exit(server):
    if _jobs and _jobs.poll() is None:
        _jobs.terminate()
