#!/usr/bin/env python3
"""Render Databases — Health.

Server exporters for Oracle, PostgreSQL, Cassandra, and Elasticsearch are absent
from Prometheus (no up series for those pods). MongoDB and Redis appear only as
client libraries: mongodb_driver_* and lettuce_command_*.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "dashboards" / "databases-health.yaml"
PROM = {"type": "prometheus", "uid": "${ds_prom}"}
NS = 'namespace=~"$namespace"'


def grid(h, w, x, y) -> dict:
    return {"h": h, "w": w, "x": x, "y": y}


def steps(*pairs: tuple[str, float | None]) -> dict:
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in pairs]}


def row(pid: int, title: str, y: int) -> dict:
    return {
        "id": pid,
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": grid(1, 24, 0, y),
        "panels": [],
    }


def text(pid: int, title: str, content: str, pos: dict) -> dict:
    return {
        "id": pid,
        "type": "text",
        "title": title,
        "transparent": True,
        "gridPos": pos,
        "options": {"mode": "markdown", "content": content},
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


def prom(ref: str, expr: str, legend: str = "") -> dict:
    return {
        "refId": ref,
        "datasource": PROM,
        "expr": expr,
        "editorMode": "code",
        "legendFormat": legend,
        "instant": False,
        "range": True,
        "exemplar": False,
    }


def timeseries(pid, title, targets, unit, pos, decimals=3, thresh=None, desc="") -> dict:
    defaults: dict = {
        "unit": unit,
        "decimals": decimals,
        "color": {"mode": "thresholds" if thresh else "palette-classic"},
        "custom": {
            "drawStyle": "line",
            "lineWidth": 2,
            "fillOpacity": 12,
            "showPoints": "never",
            "spanNulls": False,
            "stacking": {"mode": "none", "group": "A"},
            "thresholdsStyle": {"mode": "off"},
        },
    }
    if thresh:
        defaults["thresholds"] = thresh
    return {
        "id": pid,
        "type": "timeseries",
        "title": title,
        "description": desc,
        "datasource": PROM,
        "gridPos": pos,
        "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True, "calcs": []},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def stat(pid, title, expr, unit, decimals, thresh, pos, desc="") -> dict:
    return {
        "id": pid,
        "type": "stat",
        "title": title,
        "description": desc,
        "datasource": PROM,
        "gridPos": pos,
        "targets": [prom("A", expr)],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": decimals,
                "thresholds": thresh,
                "color": {"mode": "thresholds"},
                "custom": {},
            },
            "overrides": [],
        },
        "options": {
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "value",
        },
    }


NO_EXPORTER = {
    "Oracle": (
        "**No exporter.** Nothing in Prometheus identifies the `oracle` pod: no `up` target, "
        "no session gauge, and no `process_start_time_seconds`, so up/down and **up since** "
        "cannot be computed.\n\n"
        "Oracle XE first boot (datafiles and init scripts) takes several minutes. That readiness "
        "lives on the pod startup probe and is not scraped.\n\n"
        "Java services do publish `hikaricp_connections_*` (pool `HikariPool-1`) and "
        "`jdbc_connections_*`, but those series have no database label, so they are not shown as Oracle."
    ),
    "PostgreSQL": (
        "**No exporter.** No `postgres_*` / `pg_*` series and no `up` target for the `postgres` pod. "
        "Connections, latency, throughput, errors, and up/down are not available.\n\n"
        "Unlabelled Hikari pools on Java services are not treated as PostgreSQL."
    ),
    "Cassandra": (
        "**No exporter.** No Cassandra or Datastax driver series, and no `up` target for the "
        "`cassandra` pod. Connections, latency, throughput, errors, and up/down are not available."
    ),
    "Elasticsearch": (
        "**No exporter.** No Elasticsearch series, and HTTP client peers are other BankObs services, "
        "not `elasticsearch:9200`. Connections, latency, throughput, errors, and up/down are not available."
    ),
}


def build() -> dict:
    sat = steps(("green", None), ("yellow", 70), ("red", 90))
    err = steps(("green", None), ("yellow", 1), ("red", 5))
    lat = steps(("green", None), ("yellow", 0.05), ("red", 0.2))

    mongo_checked = f'sum(mongodb_driver_pool_checkedout{{{NS}}})'
    mongo_size = f'sum(mongodb_driver_pool_size{{{NS}}})'
    mongo_count = f'sum(rate(mongodb_driver_commands_seconds_count{{{NS}}}[$__rate_interval]))'
    mongo_sum = f'sum(rate(mongodb_driver_commands_seconds_sum{{{NS}}}[$__rate_interval]))'
    mongo_fail = (
        f'sum(rate(mongodb_driver_commands_seconds_count{{{NS},status!="SUCCESS"}}[$__rate_interval]))'
    )
    redis_count = f'sum(rate(lettuce_command_completion_seconds_count{{{NS}}}[$__rate_interval]))'
    redis_sum = f'sum(rate(lettuce_command_completion_seconds_sum{{{NS}}}[$__rate_interval]))'
    redis_by_cmd = (
        f'sum by (command) (rate(lettuce_command_completion_seconds_count{{{NS}}}[$__rate_interval]))'
    )

    panels: list[dict] = []
    y = 0
    pid = 1
    for name in ("Oracle", "PostgreSQL", "Cassandra", "Elasticsearch"):
        panels.append(row(pid, name, y))
        pid += 1
        h = 5 if name == "Oracle" else 3
        panels.append(text(pid, "No exporter", NO_EXPORTER[name], grid(h, 24, 0, y + 1)))
        pid += 1
        y += 1 + h

    panels.append(row(pid, "MongoDB — Java driver", y))
    pid += 1
    my = y + 1
    panels += [
        timeseries(
            pid,
            "Connections",
            [prom("A", mongo_checked, "checked out"), prom("B", mongo_size, "pool size")],
            "short",
            grid(8, 6, 0, my),
            decimals=0,
            desc="mongodb_driver_pool_checkedout vs mongodb_driver_pool_size. server_address is mongodb:27017. Not a mongod exporter.",
        ),
        stat(
            pid + 1,
            "Pool saturation",
            f"100 * ({mongo_checked}) / clamp_min({mongo_size}, 1)",
            "percent",
            0,
            sat,
            grid(8, 3, 6, my),
            "checked out / pool size",
        ),
        timeseries(
            pid + 2,
            "Command latency",
            [
                prom("A", f"({mongo_sum}) / clamp_min({mongo_count}, 1e-9)", "avg"),
                prom("B", f"max(mongodb_driver_commands_seconds_max{{{NS}}})", "max"),
            ],
            "s",
            grid(8, 5, 9, my),
            desc="Summary, not a histogram: avg is rate(sum)/rate(count). No p95 buckets are published.",
        ),
        timeseries(
            pid + 3,
            "Commands/s",
            [prom("A", mongo_count, "ops")],
            "reqps",
            grid(8, 4, 14, my),
            decimals=3,
            desc="rate of mongodb_driver_commands_seconds_count",
        ),
        stat(
            pid + 4,
            "Command errors",
            f"100 * ({mongo_fail} or vector(0)) / clamp_min({mongo_count} or vector(0), 1e-9)",
            "percent",
            2,
            err,
            grid(8, 3, 18, my),
            'status != "SUCCESS" as a percent of commands. Observed status values are SUCCESS.',
        ),
        text(
            pid + 5,
            "Up / down",
            "**No exporter.** Driver series only show that clients are publishing. There is no `up` target for the `mongodb` pod.",
            grid(8, 3, 21, my),
        ),
    ]
    pid += 6
    y = my + 8

    panels.append(row(pid, "Redis — Lettuce client", y))
    pid += 1
    ry = y + 1
    panels += [
        text(
            pid,
            "Connections",
            "**No series.** Lettuce publishes command timings only (`lettuce_command_completion_seconds_*`). There is no client-count or max-connection gauge, and no `redis_exporter`.",
            grid(8, 6, 0, ry),
        ),
        timeseries(
            pid + 1,
            "Command latency",
            [
                prom("A", f"({redis_sum}) / clamp_min({redis_count}, 1e-9)", "avg"),
                prom("B", f"max(lettuce_command_completion_seconds_max{{{NS}}})", "max"),
            ],
            "s",
            grid(8, 6, 6, ry),
            thresh=lat,
            desc="Summary avg and max. remote label is redis/<pod-ip>:6379. No histogram, so no p95.",
        ),
        timeseries(
            pid + 2,
            "Commands/s",
            [prom("A", redis_by_cmd, "{{command}}")],
            "reqps",
            grid(8, 6, 12, ry),
            decimals=3,
            desc="rate of lettuce_command_completion_seconds_count by command",
        ),
        text(
            pid + 3,
            "Errors",
            "**No error series.** Lettuce command metrics have no status or error label.",
            grid(8, 3, 18, ry),
        ),
        text(
            pid + 4,
            "Up / down",
            "**No exporter.** No `up` target for the `redis` pod. Command traffic only shows the client is calling Redis.",
            grid(8, 3, 21, ry),
        ),
    ]

    return {
        "uid": "bankobs-databases-health",
        "title": "Databases — Health",
        "description": (
            "BankObs datastores. Oracle, PostgreSQL, Cassandra, and Elasticsearch publish no "
            "exporter metrics. MongoDB is the Java driver (mongodb_driver_*) and Redis is the "
            "Lettuce client (lettuce_command_*). Hikari/JDBC pools are not assigned to a database "
            "because the series has no database label."
        ),
        "tags": ["bankobs", "databases"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-1h", "to": "now"},
        "graphTooltip": 1,
        "editable": True,
        "fiscalYearStartMonth": 0,
        "links": [],
        "annotations": {"list": []},
        "templating": {
            "list": [
                {
                    "name": "ds_prom",
                    "label": "Prometheus",
                    "type": "datasource",
                    "query": "prometheus",
                    "refresh": 1,
                    "multi": False,
                    "includeAll": False,
                    "hide": 0,
                    "current": {},
                },
                {
                    "name": "namespace",
                    "label": "Namespace",
                    "type": "query",
                    "datasource": PROM,
                    "definition": 'label_values(up{job=~"bankobs/.*"}, namespace)',
                    "query": {
                        "qryType": 1,
                        "query": 'label_values(up{job=~"bankobs/.*"}, namespace)',
                        "refId": "PrometheusVariableQueryEditor-VariableQuery",
                    },
                    "refresh": 2,
                    "sort": 1,
                    "multi": False,
                    "includeAll": False,
                    "hide": 0,
                    "current": {"selected": True, "text": "bankobs", "value": "bankobs"},
                    "options": [{"selected": True, "text": "bankobs", "value": "bankobs"}],
                },
                {
                    "name": "database",
                    "label": "Database",
                    "type": "custom",
                    "query": "Oracle,PostgreSQL,MongoDB,Cassandra,Redis,Elasticsearch",
                    "multi": True,
                    "includeAll": True,
                    "allValue": ".*",
                    "hide": 0,
                    "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                    "options": [
                        {"text": "All", "value": "$__all", "selected": True},
                        {"text": "Oracle", "value": "Oracle", "selected": False},
                        {"text": "PostgreSQL", "value": "PostgreSQL", "selected": False},
                        {"text": "MongoDB", "value": "MongoDB", "selected": False},
                        {"text": "Cassandra", "value": "Cassandra", "selected": False},
                        {"text": "Redis", "value": "Redis", "selected": False},
                        {"text": "Elasticsearch", "value": "Elasticsearch", "selected": False},
                    ],
                },
            ]
        },
        "panels": panels,
    }


def main() -> None:
    dashboard = build()
    raw = json.dumps(dashboard, indent=2)
    json.loads(raw)
    indented = "\n".join(("    " + line) if line else "" for line in raw.splitlines())
    yaml = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: bankobs-databases-health
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: "Infrastructure"
data:
  databases-health.json: |-
{indented}
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(yaml)
    print(f"wrote {OUT} ({len(raw)} bytes json)")


if __name__ == "__main__":
    main()
