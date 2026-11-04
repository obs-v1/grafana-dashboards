#!/usr/bin/env python3
"""Render the Platform Overview dashboard ConfigMap. Run from repo root."""

from __future__ import annotations

import json
from pathlib import Path

NS = 'namespace=~"$namespace",job=~"bankobs/.*"'
HIST = "http_request_duration_highr_seconds"
TIERS = (("java", "jvm_info"), ("go", "go_info"), ("python", "python_info"))

OUT = Path(__file__).resolve().parents[1] / "dashboards" / "platform-overview-golden-signals.yaml"


def tiered(selector: str) -> str:
    """Sum `selector` (must still carry `app`) and tag java/go/python."""
    parts = []
    for tier, info in TIERS:
        parts.append(
            "("
            f'label_replace(sum by (app) ({selector}), "tier", "{tier}", "app", ".+")'
            f' * on (app) group_left () (sum by (app) ({info}{{{NS}}}) > bool 0)'
            ")"
        )
    return " or ".join(parts)


def tiered_hist(selector: str) -> str:
    parts = []
    for tier, info in TIERS:
        parts.append(
            "("
            f'label_replace(sum by (app, le) ({selector}), "tier", "{tier}", "app", ".+")'
            f' * on (app) group_left () (sum by (app) ({info}{{{NS}}}) > bool 0)'
            ")"
        )
    return " or ".join(parts)


def rate(metric: str, extra: str = "") -> str:
    labels = NS if not extra else f"{NS},{extra}"
    return f"rate({metric}{{{labels}}}[$__rate_interval])"


def prom(ref: str, expr: str, legend: str = "", instant: bool = False) -> dict:
    target = {
        "refId": ref,
        "datasource": {"type": "prometheus", "uid": "${ds_prom}"},
        "expr": expr,
        "editorMode": "code",
        "instant": instant,
        "range": not instant,
        "exemplar": False,
    }
    if legend:
        target["legendFormat"] = legend
    if instant:
        target["format"] = "table"
    return target


def grid(h, w, x, y) -> dict:
    return {"h": h, "w": w, "x": x, "y": y}


def row(pid: int, title: str, y: int) -> dict:
    return {
        "id": pid,
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": grid(1, 24, 0, y),
        "panels": [],
    }


def thresholds(*steps: tuple[str, float | None]) -> dict:
    return {
        "mode": "absolute",
        "steps": [{"color": color, "value": value} for color, value in steps],
    }


def field(unit: str, decimals: int | None = None, steps=None, extra=None) -> dict:
    cfg = {"defaults": {"unit": unit, "custom": extra or {}}, "overrides": []}
    if decimals is not None:
        cfg["defaults"]["decimals"] = decimals
    if steps is not None:
        cfg["defaults"]["thresholds"] = thresholds(*steps)
        cfg["defaults"]["color"] = {"mode": "thresholds"}
    else:
        cfg["defaults"]["color"] = {"mode": "palette-classic"}
    return cfg


def ts_custom() -> dict:
    return {
        "drawStyle": "line",
        "lineInterpolation": "linear",
        "lineWidth": 2,
        "fillOpacity": 15,
        "showPoints": "never",
        "spanNulls": False,
        "stacking": {"mode": "none", "group": "A"},
        "thresholdsStyle": {"mode": "off"},
        "axisCenteredZero": False,
    }


def stat(pid, title, expr, unit, decimals, steps, pos, legend="") -> dict:
    return {
        "id": pid,
        "type": "stat",
        "title": title,
        "datasource": {"type": "prometheus", "uid": "${ds_prom}"},
        "gridPos": pos,
        "targets": [prom("A", expr, legend)],
        "fieldConfig": field(unit, decimals, steps),
        "options": {
            "colorMode": "background",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "value",
            "wideLayout": True,
        },
    }


def timeseries(pid, title, targets, unit, decimals, pos, steps=None, desc="") -> dict:
    panel = {
        "id": pid,
        "type": "timeseries",
        "title": title,
        "description": desc,
        "datasource": {"type": "prometheus", "uid": "${ds_prom}"},
        "gridPos": pos,
        "targets": targets,
        "fieldConfig": field(unit, decimals, steps, ts_custom()),
        "options": {
            "legend": {
                "displayMode": "table",
                "placement": "bottom",
                "showLegend": True,
                "calcs": ["mean", "last"],
            },
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }
    return panel


SERVICE_LINK = {
    "title": "Service RED",
    "url": (
        "/d/bankobs-service-red/service-red?${__url_time_range}"
        "&var-ds_prom=${ds_prom}&var-namespace=${namespace}"
        "&var-service=${__data.fields.service}"
    ),
    "targetBlank": False,
}


def table(pid, title, expr, value_name, unit, steps, pos) -> dict:
    return {
        "id": pid,
        "type": "table",
        "title": title,
        "description": "Row links to the Service RED dashboard, passing the service name.",
        "datasource": {"type": "prometheus", "uid": "${ds_prom}"},
        "gridPos": pos,
        "targets": [prom("A", expr, "", instant=True)],
        "transformations": [
            {
                "id": "organize",
                "options": {
                    "excludeByName": {"Time": True, "app": True},
                    "renameByName": {"Value": value_name},
                    "indexByName": {"service": 0, value_name: 1},
                },
            }
        ],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": 2 if unit == "percent" else 3,
                "thresholds": thresholds(*steps),
                "color": {"mode": "thresholds"},
                "custom": {"align": "auto", "cellOptions": {"type": "auto"}, "filterable": False},
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "service"},
                    "properties": [
                        {"id": "links", "value": [SERVICE_LINK]},
                        {"id": "custom.cellOptions", "value": {"type": "auto"}},
                    ],
                },
                {
                    "matcher": {"id": "byName", "options": value_name},
                    "properties": [
                        {
                            "id": "custom.cellOptions",
                            "value": {"type": "color-background", "mode": "basic"},
                        }
                    ],
                },
            ],
        },
        "options": {
            "showHeader": True,
            "cellHeight": "sm",
            "sortBy": [{"displayName": value_name, "desc": True}],
            "footer": {"show": False},
        },
    }


def by_service(selector: str) -> str:
    return (
        f'label_replace(sum by (app) ({selector}), "service", "$1", "app", "(.+)")'
    )


def build() -> dict:
    count_all = rate(f"{HIST}_count")
    count_5xx = rate(f"{HIST}_count", 'status=~"5.."')
    bucket = rate(f"{HIST}_bucket")

    req_tier = f"sum by (tier) ({tiered(count_all)})"
    err_tier = (
        f"100 * (sum by (tier) ({tiered(count_5xx)}) or (sum by (tier) ({tiered(count_all)}) * 0)) "
        f"/ clamp_min(sum by (tier) ({tiered(count_all)}), 1e-9)"
    )

    latency_targets = []
    for ref, q, legend in (("A", "0.50", "p50 {{tier}}"), ("B", "0.95", "p95 {{tier}}"), ("C", "0.99", "p99 {{tier}}")):
        expr = f"histogram_quantile({q}, sum by (le, tier) ({tiered_hist(bucket)}))"
        latency_targets.append(prom(ref, expr, legend))

    err_top = (
        "topk(5, 100 * ("
        f"sum by (service) ({by_service(count_5xx)}) or (sum by (service) ({by_service(count_all)}) * 0)) "
        f"/ clamp_min(sum by (service) ({by_service(count_all)}), 1e-9))"
    )
    lat_top = (
        "topk(5, histogram_quantile(0.95, sum by (le, service) ("
        'label_replace(sum by (app, le) (' + bucket + '), "service", "$1", "app", "(.+)")'
        ")))"
    )

    up = f'max by (app) (up{{{NS}}})'
    services_up = f"count(({up}) == 1) or vector(0)"
    services_down = f"count(({up}) == 0) or vector(0)"
    total_rate = f"sum({count_all}) or vector(0)"
    error_pct = (
        f"100 * (sum({count_5xx}) or vector(0)) / clamp_min(sum({count_all}) or vector(0), 1e-9)"
    )
    p95 = f"histogram_quantile(0.95, sum by (le) ({bucket}))"
    cpu = f"sum({rate('process_cpu_seconds_total')})"
    mem = f"sum(process_resident_memory_bytes{{{NS}}})"

    return {
        "uid": "bankobs-platform-overview",
        "title": "Platform Overview — Golden Signals",
        "description": (
            "Fleet golden signals for BankObs. Request rate, 5xx share, and latency "
            "use http_request_duration_highr_seconds (labels include app, namespace, "
            "job, status). Tier is java/go/python via jvm_info, go_info, and python_info "
            "joined on app. Up/down counts scrape target up for job bankobs/*. "
            "Saturation is process_cpu_seconds_total and process_resident_memory_bytes "
            "from the bankobs scrapes. Service rows open dashboard uid bankobs-service-red "
            "with var-service set."
        ),
        "tags": ["bankobs", "golden-signals"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-1h", "to": "now"},
        "graphTooltip": 1,
        "editable": True,
        "fiscalYearStartMonth": 0,
        "templating": {
            "list": [
                {
                    "name": "ds_prom",
                    "label": "Prometheus",
                    "type": "datasource",
                    "query": "prometheus",
                    "refresh": 1,
                    "regex": "",
                    "multi": False,
                    "includeAll": False,
                    "hide": 0,
                    "current": {},
                },
                {
                    "name": "namespace",
                    "label": "Namespace",
                    "type": "query",
                    "datasource": {"type": "prometheus", "uid": "${ds_prom}"},
                    "definition": 'label_values(up{job=~"bankobs/.*"}, namespace)',
                    "query": {
                        "qryType": 1,
                        "query": 'label_values(up{job=~"bankobs/.*"}, namespace)',
                        "refId": "PrometheusVariableQueryEditor-VariableQuery",
                    },
                    "refresh": 1,
                    "regex": "",
                    "sort": 1,
                    "multi": False,
                    "includeAll": False,
                    "hide": 0,
                    "current": {"selected": True, "text": "bankobs", "value": "bankobs"},
                    "options": [{"selected": True, "text": "bankobs", "value": "bankobs"}],
                },
            ]
        },
        "annotations": {"list": []},
        "links": [],
        "panels": [
            row(1, "Fleet", 0),
            stat(2, "Request rate", total_rate, "reqps", 1, [("green", None)], grid(5, 5, 0, 1)),
            stat(
                3,
                "Error %",
                error_pct,
                "percent",
                2,
                [("green", None), ("yellow", 1), ("red", 5)],
                grid(5, 5, 5, 1),
            ),
            stat(
                4,
                "p95 latency",
                p95,
                "s",
                3,
                [("green", None), ("yellow", 0.3), ("red", 1)],
                grid(5, 5, 10, 1),
            ),
            stat(5, "Services up", services_up, "none", 0, [("red", None), ("green", 1)], grid(5, 5, 15, 1)),
            stat(6, "Services down", services_down, "none", 0, [("green", None), ("red", 1)], grid(5, 4, 20, 1)),
            row(10, "Traffic by tier", 6),
            timeseries(
                11,
                "Request rate by tier",
                [prom("A", req_tier, "{{tier}}")],
                "reqps",
                2,
                grid(8, 24, 0, 7),
                desc="sum of http_request_duration_highr_seconds_count, split by runtime info metric",
            ),
            row(20, "Errors by tier", 15),
            timeseries(
                21,
                "5xx error % by tier",
                [prom("A", err_tier, "{{tier}}")],
                "percent",
                2,
                grid(8, 24, 0, 16),
                steps=[("green", None), ("yellow", 1), ("red", 5)],
                desc='status=~"5.." as a percent of all requests on the same histogram',
            ),
            row(30, "Latency by tier", 24),
            timeseries(
                31,
                "Latency by tier",
                latency_targets,
                "s",
                3,
                grid(8, 24, 0, 25),
                steps=[("green", None), ("yellow", 0.3), ("red", 1)],
                desc="histogram_quantile of http_request_duration_highr_seconds_bucket",
            ),
            row(40, "Saturation", 33),
            timeseries(
                41,
                "Process CPU",
                [prom("A", cpu, "cpu")],
                "short",
                2,
                grid(8, 12, 0, 34),
                desc="sum of process_cpu_seconds_total across scraped bankobs pods, in cores",
            ),
            timeseries(
                42,
                "Process memory",
                [prom("A", mem, "rss")],
                "bytes",
                1,
                grid(8, 12, 12, 34),
                desc="sum of process_resident_memory_bytes across scraped bankobs pods",
            ),
            row(50, "Hottest services", 42),
            table(
                51,
                "Top 5 services by error %",
                err_top,
                "Error %",
                "percent",
                [("green", None), ("yellow", 1), ("red", 5)],
                grid(8, 12, 0, 43),
            ),
            table(
                52,
                "Top 5 services by p95 latency",
                lat_top,
                "p95",
                "s",
                [("green", None), ("yellow", 0.3), ("red", 1)],
                grid(8, 12, 12, 43),
            ),
        ],
    }


def main() -> None:
    dashboard = build()
    raw = json.dumps(dashboard, indent=2)
    json.loads(raw)
    indented = "\n".join(("    " + line) if line else "" for line in raw.splitlines())
    yaml = f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: bankobs-platform-overview
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: "BankObs"
data:
  platform-overview-golden-signals.json: |-
{indented}
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(yaml)
    print(f"wrote {OUT} ({len(raw)} bytes json)")


if __name__ == "__main__":
    main()
