# Render every dashboard, then push the ConfigMaps to Grafana over HTTP.
#
#   make dashboards GRAFANA_URL=https://grafana.example GRAFANA_TOKEN=glsa_...
#
# scripts/render_*.py rebuild the YAML. scripts/apply_*.py post it.
# Any other scripts/*.py run between those two.
#
# The YAML under dashboards/ is also a kube-prometheus-stack ConfigMap
# (label grafana_dashboard=1, annotation grafana_folder). Apply that with
# kubectl only if you want the sidecar to load it:
#
#   kubectl --context obs-v1-observability apply -f dashboards/

GRAFANA_URL ?=
GRAFANA_TOKEN ?=

RENDER_SCRIPTS := $(wildcard scripts/render_*.py)
APPLY_SCRIPTS := $(wildcard scripts/apply_*.py)
OTHER_SCRIPTS := $(filter-out $(RENDER_SCRIPTS) $(APPLY_SCRIPTS),$(wildcard scripts/*.py))
PY_SCRIPTS := $(RENDER_SCRIPTS) $(OTHER_SCRIPTS) $(APPLY_SCRIPTS)

.PHONY: dashboards

dashboards:
	@test -n "$(GRAFANA_URL)" || { echo "GRAFANA_URL is required"; exit 1; }
	@test -n "$(GRAFANA_TOKEN)" || { echo "GRAFANA_TOKEN is required"; exit 1; }
	@test -n "$(PY_SCRIPTS)" || { echo "no scripts/*.py to run"; exit 1; }
	@for s in $(PY_SCRIPTS); do \
		echo "==> $$s"; \
		GRAFANA_URL="$(GRAFANA_URL)" GRAFANA_TOKEN="$(GRAFANA_TOKEN)" python3 $$s; \
	done
