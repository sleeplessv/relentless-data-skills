#!/usr/bin/env python3
"""Print the Prefect target this environment resolves to, with secrets withheld.

Run it with the project's own Python, from the project root, so Prefect
resolves settings exactly as the project's flows and CLI do:

    <project runner> python <skill-dir>/scripts/target.py

Output is one `key: value` line per fact. URLs lose their credentials, query
string, and fragment; authentication settings are reported by presence only,
so the output is safe to keep in a transcript.

Exit codes: 0 the summary was printed; 2 Prefect is not importable in this
interpreter; 3 this Prefect version's settings layout is not recognized.

Standard library only, apart from the project's own Prefect.
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit, urlunsplit

NOT_ENV = "not env (.env, prefect.toml, pyproject.toml, or profile)"


def redact_url(url: object) -> tuple[str, list[str]]:
    """Return the URL without credentials, query, or fragment, and what was cut."""
    parts = urlsplit(str(url))
    if not parts.scheme or not parts.netloc:
        return "<unparseable, withheld>", ["value"]
    stripped = []
    netloc = parts.netloc
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[1]
        stripped.append("credentials")
    if parts.query:
        stripped.append("query")
    if parts.fragment:
        stripped.append("fragment")
    return urlunsplit((parts.scheme, netloc, parts.path, "", "")), stripped


def source(env_name: str) -> str:
    """Say whether a setting comes from the process environment."""
    return f"env {env_name}" if os.environ.get(env_name) else NOT_ENV


def presence(value: object, env_name: str) -> str:
    """Report a secret by presence and source, never by value."""
    return f"set, {source(env_name)}" if value else "unset"


def target_kind(url: object, cloud_url: object, ephemeral: bool) -> str:
    if not url:
        return "ephemeral" if ephemeral else "none"
    if cloud_url and str(url).startswith(str(cloud_url)):
        return "cloud"
    return "server"


def summarize(settings: object, profile: str | None, version: str) -> list[tuple[str, str]]:
    """Build the output lines from Prefect's resolved settings object."""
    api = settings.api
    kind = target_kind(api.url, settings.cloud.api_url, bool(settings.server.ephemeral.enabled))
    lines = [("prefect_version", version), ("profile", profile or "unknown")]
    if api.url:
        shown, stripped = redact_url(api.url)
        lines.append(("api_url", shown))
        if stripped:
            lines.append(("api_url_stripped", ", ".join(stripped)))
        lines.append(("api_url_source", source("PREFECT_API_URL")))
    else:
        lines.append(("api_url", "unset"))
    lines.append(("target", kind))
    lines.append(("api_key", presence(api.key, "PREFECT_API_KEY")))
    lines.append(("auth_string", presence(api.auth_string, "PREFECT_API_AUTH_STRING")))
    headers = settings.client.custom_headers or {}
    if headers:
        names = ", ".join(sorted(str(name) for name in headers))
        lines.append(("custom_headers", f"set, {source('PREFECT_CLIENT_CUSTOM_HEADERS')}; names: {names}"))
    else:
        lines.append(("custom_headers", "unset"))
    if kind == "server" and api.key:
        lines.append(("note", "an API key is set against a non-Cloud URL; it outranks "
                              "the auth string, and self-hosted auth fails with HTTP 401"))
    if kind == "ephemeral":
        lines.append(("note", "no API URL is set; queries reach a local ephemeral server, "
                              "which is no evidence about a remote instance"))
    if kind == "none":
        lines.append(("note", "no API URL is set and ephemeral mode is off; queries have no target"))
    return lines


def main() -> int:
    try:
        import prefect
        from prefect.settings import get_current_settings
    except ImportError as exc:
        print(f"target.py: Prefect is not importable here ({exc}). Run this script "
              "with the project's Python, through the project's runner.", file=sys.stderr)
        return 2
    version = getattr(prefect, "__version__", "unknown")
    profile = None
    try:
        from prefect.context import get_settings_context
        profile = get_settings_context().profile.name
    except Exception:  # the profile is context, not the target; report it as unknown
        pass
    try:
        lines = summarize(get_current_settings(), profile, version)
    except AttributeError as exc:
        print(f"target.py: settings layout of Prefect {version} is not recognized ({exc}). "
              "Read the settings reference for this version instead.", file=sys.stderr)
        return 3
    for key, value in lines:
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
