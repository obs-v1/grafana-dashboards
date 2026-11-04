#!/usr/bin/env python3
"""Render the Service RED dashboard ConfigMap."""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "dashboards" / "service-red.yaml"

# Canonical server RED series. Labels seen on bankobs scrapes:
# service, path, status (2xx/4xx/5xx), method, app, pod, namespace, job.
# `up` and process_start_time_seconds use `app`, which matches `service`.
SEL = 'namespace=~"$namespace",job=~"bankobs/.*",service=~"$service"'
APP = 'namespace=~"$namespace",job=~"bankobs/.*",app=~"$service"'
REQ = "http_server_requests_total"
BUCKET = "http_server_request_duration_seconds_bucket"
PROM = {"type": "prometheus", "uid": "${ds_prom}"}
LOKI = {"type": "loki", "uid": "${ds_loki}"}


def grid(h, w, x, y) -> dict:
    return {"h": h, "w": w, "x": x, "y": y}


def steps(*pairs: tuple[str, float | None]) -> dict:
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in pairs]}


def prom(ref: str, expr: str, legend: str = "", instant: bool = False, fmt: str = "time_series") -> dict:
    target = {
        "refId": ref,
        "datasource": PROM,
        "expr": expr,
        "editorMode": "code",
        "legendFormat": legend,
        "instant": instant,
        "range": not instant,
        "exemplar": False,
        "format": fmt,
    }
    return target


def row(pid: int, title: str, y: int) -> dict:
    return {"id": pid, "type": "row", "title": title, "collapsed": False, "gridPos": grid(1, 24, 0, y), "panels": []}


def field(unit: str, decimals: int | None = None, thresh=None) -> dict:
    cfg: dict = {
        "defaults": {
            "unit": unit,
            "color": {"mode": "thresholds" if thresh else "palette-classic"},
            "custom": {
                "drawStyle": "line",
                "lineWidth": 2,
                "fillOpacity": 12,
                "showPoints": "never",
                "spanNulls": False,
                "stacking": {"mode": "none", "group": "A"},
                "thresholdsStyle": {"mode": "line" if thresh else "off"},
            },
        },
        "overrides": [],
    }
    if decimals is not None:
        cfg["defaults"]["decimals"] = decimals
    if thresh is not None:
        cfg["defaults"]["thresholds"] = thresh
    return cfg


def timeseries(pid, title, targets, unit, decimals, pos, thresh=None, desc="", links=None) -> dict:
    panel = {
        "id": pid,
        "type": "timeseries",
        "title": title,
        "description": desc,
        "datasource": PROM,
        "gridPos": pos,
        "targets": targets,
        "fieldConfig": field(unit, decimals, thresh),
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True, "calcs": []},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }
    if links:
        panel["links"] = links
        panel["fieldConfig"]["defaults"]["links"] = links
    return panel


def stat(pid, title, expr, unit, decimals, thresh, pos, desc="") -> dict:
    return {
        "id": pid,
        "type": "stat",
        "title": title,
        "description": desc,
        "datasource": PROM,
        "gridPos": pos,
        "targets": [prom("A", expr)],
        "fieldConfig": field(unit, decimals, thresh),
        "options": {
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "value",
        },
    }


def jaeger_explore() -> str:
    panes = {
        "j": {
            "datasource": "${ds_jaeger}",
            "queries": [
                {
                    "refId": "A",
                    "datasource": {"type": "jaeger", "uid": "${ds_jaeger}"},
                    "queryType": "traceql",
                    "query": '{ resource.service.name =~ "${service}" }',
                }
            ],
            "range": {"from": "now-1h", "to": "now"},
        }
    }
    encoded = urllib.parse.quote(json.dumps(panes, separators=(",", ":")))
    # Leave Grafana template tokens literal so they interpolate before navigation.
    encoded = encoded.replace("%24%7B", "${").replace("%7D", "}")
    return f"/explore?schemaVersion=1&orgId=1&panes={encoded}"


TRACE_LINKS = [
    {
        "title": "Trace / Latency",
        "url": (
            "/d/bankobs-trace-latency/trace-latency?${__url_time_range}"
            "&var-ds_prom=${ds_prom}&var-ds_jaeger=${ds_jaeger}"
            "&var-namespace=${namespace}&var-service=${service}"
        ),
        "targetBlank": False,
        "keepTime": True,
        "type": "link",
    },
    {
        "title": "Jaeger",
        "url": jaeger_explore(),
        "targetBlank": False,
        "keepTime": True,
        "type": "link",
    },
]


def build() -> dict:
    rate_all = f"rate({REQ}{{{SEL}}}[$__rate_interval])"
    rate_err = f'rate({REQ}{{{SEL},status=~"4xx|5xx"}}[$__rate_interval])'
    rate_5xx = f'rate({REQ}{{{SEL},status="5xx"}}[$__rate_interval])'
    buckets = f"rate({BUCKET}{{{SEL}}}[$__rate_interval])"

    by_path = f"sum by (path) ({rate_all})"
    by_status = f"sum by (status) ({rate_all})"
    err_split = f"sum by (status) ({rate_err})"
    err_pct = (
        f"100 * (sum({rate_5xx}) or vector(0)) / clamp_min(sum({rate_all}) or vector(0), 1e-9)"
    )
    err_rps = f"sum({rate_err}) or vector(0)"
    pods = f"count(up{{{APP}}} == 1) or vector(0)"
    restarts = f"sum(changes(process_start_time_seconds{{{APP}}}[$__range])) or vector(0)"

    latency = []
    for ref, q, legend in (("A", "0.50", "p50"), ("B", "0.95", "p95"), ("C", "0.99", "p99")):
        latency.append(
            prom(ref, f"histogram_quantile({q}, sum by (le) ({buckets}))", legend)
        )

    err_thresh = steps(("green", None), ("yellow", 1), ("red", 5))
    lat_thresh = steps(("green", None), ("yellow", 0.3), ("red", 1))

    return {
        "uid": "bankobs-service-red",
        "title": "Service RED",
        "description": (
            "Per-service rate, errors, and duration from http_server_requests_total "
            "and http_server_request_duration_seconds (labels: service, path, status "
            "as 2xx/4xx/5xx). Pods are scrape targets up. Process restarts are changes "
            "in process_start_time_seconds; kube-state restart series are not scraped "
            "for bankobs. Error logs are Loki streams with service_name and detected_level=error."
        ),
        "tags": ["bankobs", "red"],
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
                    "name": "ds_loki",
                    "label": "Loki",
                    "type": "datasource",
                    "query": "loki",
                    "refresh": 1,
                    "multi": False,
                    "includeAll": False,
                    "hide": 0,
                    "current": {},
                },
                {
                    "name": "ds_jaeger",
                    "label": "Jaeger",
                    "type": "datasource",
                    "query": "jaeger",
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
                    "definition": 'label_values(http_server_requests_total{job=~"bankobs/.*"}, namespace)',
                    "query": {
                        "qryType": 1,
                        "query": 'label_values(http_server_requests_total{job=~"bankobs/.*"}, namespace)',
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
                    "name": "service",
                    "label": "Service",
                    "type": "query",
                    "datasource": PROM,
                    "definition": 'label_values(http_server_requests_total{namespace=~"$namespace",job=~"bankobs/.*"}, service)',
                    "query": {
                        "qryType": 1,
                        "query": 'label_values(http_server_requests_total{namespace=~"$namespace",job=~"bankobs/.*"}, service)',
                        "refId": "PrometheusVariableQueryEditor-VariableQuery",
                    },
                    "refresh": 2,
                    "sort": 1,
                    "multi": True,
                    "includeAll": True,
                    "allValue": ".*",
                    "hide": 0,
                    "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
                },
            ]
        },
        "panels": [
            row(1, "Rate", 0),
            timeseries(
                2,
                "Requests/s by endpoint",
                [prom("A", by_path, "{{path}}")],
                "reqps",
                2,
                grid(8, 14, 0, 1),
                desc="http_server_requests_total by path",
            ),
            timeseries(
                3,
                "Requests/s by status class",
                [prom("A", by_status, "{{status}}")],
                "reqps",
                2,
                grid(8, 10, 14, 1),
                desc="status is already a class: 2xx, 4xx, 5xx",
            ),
            row(10, "Errors", 9),
            stat(11, "Error %", err_pct, "percent", 2, err_thresh, grid(4, 6, 0, 10), "5xx as a percent of all requests"),
            stat(12, "Errors/s", err_rps, "reqps", 2, steps(("green", None), ("yellow", 0.05), ("red", 0.5)), grid(4, 6, 6, 10), "4xx + 5xx request rate"),
            stat(13, "Pods up", pods, "none", 0, steps(("red", None), ("green", 1)), grid(4, 6, 12, 10), "scrape targets with up==1"),
            stat(
                14,
                "Process restarts",
                restarts,
                "none",
                0,
                steps(("green", None), ("red", 1)),
                grid(4, 6, 18, 10),
                "changes of process_start_time_seconds over the selected range",
            ),
            timeseries(
                15,
                "4xx vs 5xx",
                [prom("A", err_split, "{{status}}")],
                "reqps",
                3,
                grid(7, 24, 0, 14),
                desc="No exception counter is exported on the server histogram; status class is the error split",
            ),
            row(20, "Duration", 21),
            timeseries(
                21,
                "Latency",
                latency,
                "s",
                3,
                grid(8, 14, 0, 22),
                thresh=lat_thresh,
                desc="histogram_quantile of http_server_request_duration_seconds_bucket",
                links=TRACE_LINKS,
            ),
            {
                "id": 22,
                "type": "heatmap",
                "title": "Latency heatmap",
                "description": "http_server_request_duration_seconds_bucket",
                "datasource": PROM,
                "gridPos": grid(8, 10, 14, 22),
                "targets": [prom("A", f"sum by (le) ({buckets})", "{{le}}", fmt="heatmap")],
                "fieldConfig": {"defaults": {"unit": "s", "custom": {}}, "overrides": []},
                "options": {
                    "calculate": False,
                    "calculation": {},
                    "cellGap": 1,
                    "color": {
                        "mode": "scheme",
                        "scheme": "Oranges",
                        "steps": 64,
                        "fill": "dark-orange",
                    },
                    "yAxis": {"unit": "s", "decimals": 3},
                    "tooltip": {"show": True, "yHistogram": False},
                    "legend": {"show": True},
                    "exemplars": {"color": "rgba(255,0,255,0.7)"},
                    "filterValues": {"le": 1e-9},
                    "rowsFrame": {"layout": "auto"},
                },
            },
            row(30, "Logs", 30),
            {
                "id": 31,
                "type": "logs",
                "title": "Recent error logs",
                "description": "Loki streams for the selected service with detected_level=error",
                "datasource": LOKI,
                "gridPos": grid(10, 24, 0, 31),
                "targets": [
                    {
                        "refId": "A",
                        "datasource": LOKI,
                        "expr": '{k8s_namespace_name=~"$namespace",service_name=~"$service"} | detected_level="error"',
                        "queryType": "range",
                        "maxLines": 100,
                    }
                ],
                "options": {
                    "showTime": True,
                    "showLabels": False,
                    "showCommonLabels": False,
                    "wrapLogMessage": True,
                    "prettifyLogMessage": True,
                    "enableLogDetails": True,
                    "dedupStrategy": "none",
                    "sortOrder": "Descending",
                },
            },
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
  name: bankobs-service-red
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: "BankObs"
data:
  service-red.json: |-
{indented}
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(yaml)
    print(f"wrote {OUT} ({len(raw)} bytes json)")


if __name__ == "__main__":
    main()
