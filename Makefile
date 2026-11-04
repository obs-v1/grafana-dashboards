# Push sidecar dashboard ConfigMaps to Grafana over HTTP.
#
#   make dashboards GRAFANA_URL=https://grafana.example GRAFANA_TOKEN=glsa_...
#
# The YAML under dashboards/ is also a kube-prometheus-stack ConfigMap
# (label grafana_dashboard=1, annotation grafana_folder). Apply that with
# kubectl only if you want the sidecar to load it:
#
#   kubectl --context obs-v1-observability apply -f dashboards/

GRAFANA_URL ?=
GRAFANA_TOKEN ?=

.PHONY: dashboards

dashboards:
	@test -n "$(GRAFANA_URL)" || { echo "GRAFANA_URL is required"; exit 1; }
	@test -n "$(GRAFANA_TOKEN)" || { echo "GRAFANA_TOKEN is required"; exit 1; }
	GRAFANA_URL="$(GRAFANA_URL)" GRAFANA_TOKEN="$(GRAFANA_TOKEN)" python3 scripts/apply_dashboards.py
