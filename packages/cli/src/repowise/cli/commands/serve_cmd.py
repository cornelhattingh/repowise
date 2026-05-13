"""``repowise serve`` — start the API server and web UI."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import click

from repowise.cli import __version__
from repowise.cli.helpers import console, load_config

_log = logging.getLogger(__name__)


def _get_global_config_dir() -> Path:
    """Get the global RepoWise config directory.
    
    Respects REPOWISE_CONFIG_DIR env var if set, otherwise defaults to ~/.repowise.
    This allows centralized config management across multiple repositories.
    """
    config_dir = os.environ.get("REPOWISE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir).resolve()
    return Path.home() / ".repowise"


def _load_env_file() -> None:
    """Load .env from the config directory into os.environ (without overwriting).

    Checks REPOWISE_CONFIG_DIR first, then falls back to the local .repowise/ directory.
    This must be called before any code reads environment variables.
    """
    from repowise.cli.ui import load_dotenv

    config_dir = os.environ.get("REPOWISE_CONFIG_DIR")
    if config_dir:
        env_file = Path(config_dir) / ".env"
        if env_file.exists():
            # load_dotenv expects a repo dir and appends .repowise/.env, so we handle it directly
            _load_env_from_file(env_file)
            return

    # Fall back to local .repowise/.env
    local_repowise = Path.cwd() / ".repowise"
    if local_repowise.exists():
        load_dotenv(local_repowise.parent)


def _load_env_from_file(env_file: Path) -> None:
    """Load a .env file directly into os.environ (without overwriting existing vars)."""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        raw_value = raw_value.strip()
        # Strip inline comments (only if # is preceded by whitespace)
        hash_idx = raw_value.find(" #")
        if hash_idx == -1:
            hash_idx = raw_value.find("\t#")
        if hash_idx >= 0:
            raw_value = raw_value[:hash_idx].rstrip()
        # Strip matching surrounding quotes
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in ('"', "'"):
            raw_value = raw_value[1:-1]
        # Don't overwrite existing env vars
        if key and raw_value and key not in os.environ:
            os.environ[key] = raw_value

_GLOBAL_CONFIG_DIR = Path.home() / ".repowise"  # Will be overridden by _setup_embedder()


def _setup_embedder() -> None:
    """Ensure REPOWISE_EMBEDDER is set before the server starts.

    Priority:
      1. Already set in environment → nothing to do.
      2. Saved in global config directory (respects REPOWISE_CONFIG_DIR) → restore it (and its API key).
      3. Prompt the user interactively → save choice for next time.
    """
    if os.environ.get("REPOWISE_EMBEDDER"):
        return

    # Get the global config directory (checks REPOWISE_CONFIG_DIR env var at runtime)
    global_config_dir = _get_global_config_dir()
    config_file = global_config_dir / "config.yaml"
    
    # Debug output
    console.print(f"[dim]Config directory: {global_config_dir}[/dim]")
    console.print(f"[dim]Config file: {config_file}[/dim]")
    console.print(f"[dim]Config file exists: {config_file.exists()}[/dim]")
    
    # Check global config saved by a previous serve/init run.
    cfg = load_config(global_config_dir)
    if cfg:
        console.print(f"[dim]Loaded config: {cfg}[/dim]")
    else:
        console.print("[dim]No config found[/dim]")
    
    saved_embedder = cfg.get("embedder", "")
    if saved_embedder and saved_embedder != "mock":
        console.print(f"[green]Using embedder from config: {saved_embedder}[/green]")
        os.environ["REPOWISE_EMBEDDER"] = saved_embedder
        # Restore API key if saved alongside the config.
        if cfg.get("embedder_api_key"):
            _set_api_key_env(saved_embedder, cfg["embedder_api_key"])
        # Restore base URL for openai_compatible
        if saved_embedder == "openai_compatible" and cfg.get("embedder_base_url"):
            console.print(f"[green]Using base URL from config: {cfg.get('embedder_base_url')}[/green]")
            os.environ.setdefault("OPENAI_COMPATIBLE_BASE_URL", cfg["embedder_base_url"])
        _log_openai_compatible_config()
        return

    # Detect which providers already have keys in the environment.
    has_gemini = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_openrouter = bool(os.environ.get("OPENROUTER_API_KEY"))
    has_compatible_url = bool(
        os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    )

    console.print(
        "\n[bold]Chat & search require an embedder.[/bold] "
        "Choose one or skip (other features still work).\n"
    )

    options = []
    labels = []
    if has_gemini:
        options.append("gemini")
        labels.append("[1] gemini                [green]✓ key set[/green]")
    else:
        options.append("gemini")
        labels.append("[1] gemini                [dim]needs GEMINI_API_KEY / GOOGLE_API_KEY[/dim]")
    if has_openai:
        options.append("openai")
        labels.append("[2] openai                [green]✓ key set[/green]")
    else:
        options.append("openai")
        labels.append("[2] openai                [dim]needs OPENAI_API_KEY[/dim]")
    if has_openrouter:
        options.append("openrouter")
        labels.append("[3] openrouter            [green]✓ key set[/green]")
    else:
        options.append("openrouter")
        labels.append("[3] openrouter            [dim]needs OPENROUTER_API_KEY[/dim]")
    if has_compatible_url:
        options.append("openai_compatible")
        labels.append("[4] openai_compatible     [green]✓ base URL set[/green]")
    else:
        options.append("openai_compatible")
        labels.append("[4] openai_compatible     [dim]needs base URL[/dim]")
    options.append("skip")
    labels.append(f"[{len(options)}] skip                  [dim]no chat/search[/dim]")

    for label in labels:
        console.print(f"  {label}")
    console.print()

    default = "1" if (has_gemini or has_openai) else "3"
    raw = click.prompt("  Select", default=default).strip()

    # Map number or name to option.
    choice = (
        raw
        if raw in options
        else (options[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(options) else "skip")
    )

    if choice == "skip":
        console.print("[dim]Skipping embedder — chat and search will be unavailable.[/dim]\n")
        return

    os.environ["REPOWISE_EMBEDDER"] = choice

    # For openai_compatible, also prompt for base URL if not set
    base_url = ""
    if choice == "openai_compatible":
        existing_url = os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or os.environ.get(
            "OPENAI_BASE_URL"
        )
        if not existing_url:
            base_url = click.prompt("  Base URL (e.g. http://localhost:11434/v1)").strip()
            if base_url:
                os.environ["OPENAI_COMPATIBLE_BASE_URL"] = base_url
        else:
            base_url = existing_url

    # Ensure the API key is present; prompt if missing.
    api_key = _get_or_prompt_api_key(choice)
    if api_key:
        _set_api_key_env(choice, api_key)

    # Save choice (and key) to ~/.repowise/config.yaml for future runs.
    _save_global_embedder(choice, api_key, base_url)
    _log_openai_compatible_config()
    console.print()


def _get_or_prompt_api_key(embedder: str) -> str:
    """Return existing API key for *embedder* or prompt the user for one."""
    if embedder == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if key:
            return key
        return click.prompt("  GEMINI_API_KEY", default="", show_default=False).strip()
    if embedder == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if key:
            return key
        return click.prompt("  OPENAI_API_KEY", default="", show_default=False).strip()
    if embedder == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if key:
            return key
        return click.prompt("  OPENROUTER_API_KEY", default="", show_default=False).strip()
    if embedder == "openai_compatible":
        key = os.environ.get("OPENAI_COMPATIBLE_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        if key:
            return key
        return click.prompt(
            "  API key (leave blank if not required)", default="", show_default=False
        ).strip()
    return ""


def _set_api_key_env(embedder: str, key: str) -> None:
    if not key:
        return
    if embedder == "gemini":
        os.environ.setdefault("GEMINI_API_KEY", key)
    elif embedder == "openai":
        os.environ.setdefault("OPENAI_API_KEY", key)
    elif embedder == "openrouter":
        os.environ.setdefault("OPENROUTER_API_KEY", key)
    elif embedder == "openai_compatible":
        os.environ.setdefault("OPENAI_COMPATIBLE_API_KEY", key)


def _log_openai_compatible_config() -> None:
    """Log the configured OpenAI-compatible base URL during startup."""
    base_url = os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    if base_url:
        _log.info(f"OpenAI-compatible base URL: {base_url}")


def _save_global_embedder(embedder: str, api_key: str, base_url: str = "") -> None:
    """Persist embedder choice to global config directory (respects REPOWISE_CONFIG_DIR)."""
    global_config_dir = _get_global_config_dir()
    global_config_dir.mkdir(parents=True, exist_ok=True)
    config_path = global_config_dir / "config.yaml"
    try:
        existing: dict = {}
        if config_path.exists():
            import yaml  # type: ignore[import-untyped]

            existing = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        existing["embedder"] = embedder
        if api_key:
            existing["embedder_api_key"] = api_key
        if base_url:
            existing["embedder_base_url"] = base_url
        import yaml  # type: ignore[import-untyped]

        config_path.write_text(
            yaml.dump(existing, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # Non-fatal — user just gets prompted again next time.


_GITHUB_REPO = "repowise-dev/repowise"
_WEB_CACHE_DIR = Path.home() / ".repowise" / "web"
_MARKER_FILE = _WEB_CACHE_DIR / ".version"


def _node_available() -> str | None:
    """Return the path to node binary, or None."""
    return shutil.which("node")


def _npm_available() -> str | None:
    """Return the path to npm binary, or None."""
    return shutil.which("npm")


def _web_is_cached(version: str) -> bool:
    """Check if the web frontend is cached and matches the current version."""
    server_js = _WEB_CACHE_DIR / "server.js"
    if not server_js.exists():
        return False
    return _MARKER_FILE.exists() and _MARKER_FILE.read_text().strip() == version


def _find_local_web() -> Path | None:
    """Check if running from the repo with packages/web available."""
    # Check from both __file__ (source installs) and cwd (pip-installed runs)
    roots = [Path(__file__).resolve(), Path.cwd().resolve()]
    for start in roots:
        candidate = start
        for _ in range(10):
            candidate = candidate.parent
            pkg_web = candidate / "packages" / "web"
            if (pkg_web / "package.json").exists():
                # Next.js standalone in monorepos nests server under package path
                standalone = pkg_web / ".next" / "standalone" / "packages" / "web" / "server.js"
                if standalone.exists():
                    return pkg_web
                return pkg_web  # exists but may need build
    return None


def _local_build_is_stale(web_dir: Path) -> bool:
    """True if the local .next/standalone bundle is older than any input source.

    Compares the standalone server.js mtime against the newest mtime under the
    source roots that get compiled into the bundle (web/ui/types packages plus
    web's config files). Skips node_modules / .next / .turbo. Used so that a
    cloned monorepo with stale build artifacts falls back to the released
    tarball instead of serving a bundle behind the user's source tree.
    """
    standalone = web_dir / ".next" / "standalone" / "packages" / "web" / "server.js"
    if not standalone.exists():
        return True
    build_mtime = standalone.stat().st_mtime

    repo_root = web_dir.parent.parent  # packages/web → repo root
    skip_dirs = {"node_modules", ".next", ".turbo", "dist", ".git"}

    file_inputs: list[Path] = [
        web_dir / "package.json",
        web_dir / "next.config.ts",
        web_dir / "next.config.js",
        web_dir / "tsconfig.json",
    ]
    dir_inputs: list[Path] = [
        web_dir / "src",
        web_dir / "app",
        web_dir / "components",
        web_dir / "lib",
        web_dir / "public",
        repo_root / "packages" / "ui" / "src",
        repo_root / "packages" / "types" / "src",
    ]

    for f in file_inputs:
        if f.exists() and f.is_file() and f.stat().st_mtime > build_mtime:
            return True

    for root in dir_inputs:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if any(part in skip_dirs for part in path.parts):
                continue
            try:
                if path.is_file() and path.stat().st_mtime > build_mtime:
                    return True
            except OSError:
                continue
    return False


def _download_web(version: str) -> bool:
    """Download pre-built web frontend from GitHub releases."""
    import httpx

    tag = f"v{version}"
    url = f"https://github.com/{_GITHUB_REPO}/releases/download/{tag}/repowise-web.tar.gz"

    console.print(f"[dim]Downloading web UI ({url})...[/dim]")
    try:
        tmp_path = None
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name
            with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes(chunk_size=65536):
                    tmp.write(chunk)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        console.print(f"[yellow]Could not download web UI: {exc}[/yellow]")
        if tmp_path:
            os.unlink(tmp_path)
        return False

    try:
        _WEB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Clean old cache
        for item in _WEB_CACHE_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        with tarfile.open(tmp_path, "r:gz") as tar:
            tar.extractall(_WEB_CACHE_DIR)

        _MARKER_FILE.write_text(version)
        console.print("[green]Web UI downloaded and cached.[/green]")
        return True
    except Exception as exc:
        console.print(f"[yellow]Failed to extract web UI: {exc}[/yellow]")
        return False
    finally:
        os.unlink(tmp_path)


def _build_local_web(web_dir: Path, npm: str) -> bool:
    """Build the Next.js frontend from source."""
    console.print("[dim]Building web UI (first time only)...[/dim]")
    try:
        # Install deps if needed
        if not (web_dir / "node_modules").exists():
            subprocess.run(
                [npm, "install"],
                cwd=str(web_dir),
                check=True,
                capture_output=True,
            )
        # Build
        subprocess.run(
            [npm, "run", "build"],
            cwd=str(web_dir),
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        console.print(f"[yellow]Web UI build failed: {exc}[/yellow]")
        return False


def _start_frontend(
    node: str,
    backend_port: int,
    frontend_port: int,
    local_web: Path | None = None,
) -> subprocess.Popen | None:
    """Start the Next.js frontend server. Returns the process or None.

    If ``local_web`` is provided, the local monorepo build is used as Option 1.
    Pass ``None`` to skip the local build (e.g. when it's stale or refresh was
    forced) and use only the cached tarball at ``~/.repowise/web``.
    """
    env = {
        **os.environ,
        "REPOWISE_API_URL": f"http://localhost:{backend_port}",
        "HOSTNAME": "0.0.0.0",
        "PORT": str(frontend_port),
    }

    # Option 1: Local repo build (preferred — uses latest source)
    if local_web:
        standalone_dir = local_web / ".next" / "standalone"
        server_js = standalone_dir / "packages" / "web" / "server.js"
        if server_js.exists():
            # Copy static files into standalone (Next.js requirement)
            static_src = local_web / ".next" / "static"
            static_dst = standalone_dir / "packages" / "web" / ".next" / "static"
            if static_src.exists() and not static_dst.exists():
                shutil.copytree(str(static_src), str(static_dst))
            public_src = local_web / "public"
            public_dst = standalone_dir / "packages" / "web" / "public"
            if public_src.exists() and not public_dst.exists():
                shutil.copytree(str(public_src), str(public_dst))

            return subprocess.Popen(
                [node, str(server_js)],
                cwd=str(standalone_dir / "packages" / "web"),
                env=env,
            )

    # Option 2: Cached download (fallback for pip-installed users)
    cached_server = _WEB_CACHE_DIR / "server.js"
    if cached_server.exists():
        return subprocess.Popen(
            [node, str(cached_server)],
            cwd=str(_WEB_CACHE_DIR),
            env=env,
        )

    return None


@click.command("serve")
@click.option("--port", default=7337, type=int, help="API server port.")
@click.option("--host", default="127.0.0.1", help="Host to bind to.")
@click.option("--workers", default=1, type=int, help="Number of uvicorn workers.")
@click.option("--ui-port", default=3000, type=int, help="Web UI port.")
@click.option("--no-ui", is_flag=True, help="Start API server only, skip the web UI.")
@click.option(
    "--refresh-ui",
    is_flag=True,
    help="Force re-download of the web UI tarball, ignoring any cache.",
)
def serve_command(
    port: int, host: str, workers: int, ui_port: int, no_ui: bool, refresh_ui: bool
) -> None:
    """Start the repowise server with the web UI.

    Starts the API backend and automatically launches the web frontend.
    The web UI is downloaded and cached on first run (~50 MB, one-time).

    Use --no-ui to start only the API server.
    """
    # Load .env from REPOWISE_CONFIG_DIR (or local .repowise/) before anything else.
    # This must happen first so env vars are available for logging setup and all downstream code.
    _load_env_file()

    # Configure logging (must be done before any loggers are used)
    log_level = os.environ.get("REPOWISE_LOG_LEVEL", "INFO").upper()
    if os.environ.get("REPOWISE_DEBUG", "").lower() == "true":
        log_level = "DEBUG"
    
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _log.info(f"RepoWise server starting (log level: {log_level})")
    
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn is not installed. Install it with: pip install repowise[/red]")
        raise SystemExit(1) from None

    _setup_embedder()

    # Auto-detect database paths based on REPOWISE_CONFIG_DIR or local .repowise/
    if not os.environ.get("REPOWISE_DB_URL"):
        # First priority: centralized REPOWISE_CONFIG_DIR
        config_dir = os.environ.get("REPOWISE_CONFIG_DIR")
        if config_dir:
            config_dir_path = Path(config_dir).resolve()
            db_path = config_dir_path / "wiki.db"
            lancedb_path = config_dir_path / "lancedb"
            graph_path = config_dir_path / "graphs"
            
            os.environ["REPOWISE_DB_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
            os.environ.setdefault("LANCEDB_PATH", str(lancedb_path))
            os.environ.setdefault("GRAPH_PATH", str(graph_path))
            
            console.print(f"[dim]Using centralized config: {config_dir_path}[/dim]")
            console.print(f"[dim]  Database: {db_path}[/dim]")
            console.print(f"[dim]  Vector store: {lancedb_path}[/dim]")
            console.print(f"[dim]  Graphs: {graph_path}[/dim]")
        else:
            # Fall back to local .repowise/ directory
            local_repowise = Path.cwd() / ".repowise"
            if local_repowise.exists():
                local_db = local_repowise / "wiki.db"
                os.environ["REPOWISE_DB_URL"] = f"sqlite+aiosqlite:///{local_db.as_posix()}"
                console.print(f"[dim]Using local database: {local_db}[/dim]")

    frontend_proc: subprocess.Popen | None = None

    if not no_ui:
        node = _node_available()
        npm = _npm_available()

        if not node:
            console.print(
                "[yellow]Node.js not found — starting API server only.[/yellow]\n"
                "[dim]To get the web UI, install Node.js 20+ or use Docker:\n"
                "  docker run -p 7337:7337 -p 3000:3000 -v .repowise:/data repowise[/dim]"
            )
        else:
            # Try to get the frontend running
            ready = False
            local_web: Path | None = None if refresh_ui else _find_local_web()

            # Option 1: Local repo build (preferred — uses latest source).
            # Only honoured when the bundle isn't behind the source tree.
            if local_web:
                if _local_build_is_stale(local_web):
                    if npm:
                        console.print(
                            "[dim]Local web bundle is older than source — rebuilding...[/dim]"
                        )
                        ready = _build_local_web(local_web, npm)
                        if not ready:
                            console.print(
                                "[yellow]Local rebuild failed — falling back to "
                                "released tarball.[/yellow]"
                            )
                            local_web = None
                    else:
                        console.print(
                            "[yellow]Local web bundle is stale and npm not found — "
                            "falling back to released tarball.[/yellow]"
                        )
                        local_web = None
                else:
                    ready = True

            # Option 2: Cached download (skip when --refresh-ui is set).
            if not ready and not refresh_ui and _web_is_cached(__version__):
                ready = True

            # Option 3: Download from GitHub releases.
            if not ready:
                ready = _download_web(__version__)

            if ready:
                frontend_proc = _start_frontend(node, port, ui_port, local_web=local_web)
                if frontend_proc:
                    console.print(f"[green]Web UI starting on http://localhost:{ui_port}[/green]")
                else:
                    console.print("[yellow]Could not start web UI — running API only.[/yellow]")
            else:
                console.print(
                    "[yellow]Web UI not available — starting API server only.[/yellow]\n"
                    "[dim]The web UI will be available in a future release.\n"
                    "For now, use Docker for the full experience:[/dim]\n"
                    f"[dim]  docker build -t repowise https://github.com/{_GITHUB_REPO}.git\n"
                    "  docker run -p 7337:7337 -p 3000:3000 -v .repowise:/data repowise[/dim]"
                )

    console.print(f"[green]API server starting on http://{host}:{port}[/green]")

    try:
        uvicorn.run(
            "repowise.server.app:create_app",
            factory=True,
            host=host,
            port=port,
            workers=workers,
            log_level="info",
        )
    finally:
        if frontend_proc:
            frontend_proc.terminate()
            frontend_proc.wait(timeout=5)
