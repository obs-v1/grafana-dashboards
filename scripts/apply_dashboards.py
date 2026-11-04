#!/usr/bin/env python3
"""Push dashboard ConfigMaps in dashboards/ to a Grafana HTTP API.

Reads each ConfigMap labelled grafana_dashboard=1, creates the folder named by
the grafana_folder annotation, and POSTs the dashboard JSON.

  GRAFANA_URL   base URL, no trailing path
  GRAFANA_TOKEN service-account token (sent as Authorization: Bearer)
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DASHBOARDS = ROOT / "dashboards"


def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def request(url: str, token: str, method: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        die(f"{method} {url} -> HTTP {exc.code}: {detail}")


def folder_uid(base: str, token: str, title: str) -> str:
    folders = request(f"{base}/api/folders", token, "GET")
    if isinstance(folders, dict):
        die(f"unexpected /api/folders response: {folders}")
    for folder in folders:
        if folder.get("title") == title:
            return folder["uid"]
    slug = "bankobs" if title == "BankObs" else title.lower().replace(" ", "-")
    created = request(
        f"{base}/api/folders",
        token,
        "POST",
        {"uid": slug, "title": title},
    )
    if "uid" in created:
        return created["uid"]
    return created["folder"]["uid"]


def dashboards() -> list[tuple[str, str, dict]]:
    found = []
    paths = sorted(DASHBOARDS.glob("*.yaml"))
    if not paths:
        die(f"no dashboard YAML in {DASHBOARDS}")
    for path in paths:
        doc = yaml.safe_load(path.read_text())
        meta = doc.get("metadata") or {}
        labels = meta.get("labels") or {}
        if str(labels.get("grafana_dashboard")) != "1":
            continue
        folder = (meta.get("annotations") or {}).get("grafana_folder") or "BankObs"
        data = doc.get("data") or {}
        if len(data) != 1:
            die(f"{path.name}: expected exactly one data key, got {list(data)}")
        raw = next(iter(data.values()))
        dashboard = json.loads(raw)
        found.append((path.name, folder, dashboard))
    if not found:
        die("no ConfigMaps labelled grafana_dashboard=1")
    return found


def main() -> None:
    base = os.environ.get("GRAFANA_URL", "").strip().rstrip("/")
    token = os.environ.get("GRAFANA_TOKEN", "").strip()
    if not base or not token:
        die("GRAFANA_URL and GRAFANA_TOKEN are required")

    folders: dict[str, str] = {}
    for name, folder, dashboard in dashboards():
        if folder not in folders:
            folders[folder] = folder_uid(base, token, folder)
        dashboard.pop("id", None)
        payload = {
            "dashboard": dashboard,
            "folderUid": folders[folder],
            "overwrite": True,
            "message": f"apply {name}",
        }
        result = request(f"{base}/api/dashboards/db", token, "POST", payload)
        print(f"{name} -> {result.get('status')} {result.get('url', result.get('uid', ''))}")


if __name__ == "__main__":
    main()
