#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ERPNEXT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
UK_PO="$ERPNEXT_DIR/erpnext/locale/uk.po"
DOCKER_DIR="${1:-$ERPNEXT_DIR/../frappe_docker}"

if [ ! -f "$UK_PO" ]; then
    echo "ERROR: uk.po not found at $UK_PO"
    exit 1
fi

if [ ! -f "$DOCKER_DIR/pwd.yml" ]; then
    echo "ERROR: frappe_docker not found at $DOCKER_DIR"
    echo "Usage: $0 [path/to/frappe_docker]"
    exit 1
fi

cd "$DOCKER_DIR"

echo "==> Starting ERPNext..."
docker compose -f pwd.yml up -d

echo "==> Waiting for site creation (this takes 2-3 minutes)..."
timeout 300 bash -c '
while ! docker compose -f pwd.yml exec -T backend bench --site frontend list-apps 2>/dev/null | grep -q erpnext; do
    echo "  waiting for site..."
    sleep 10
done
' || { echo "Timed out waiting for site. Check: docker compose -f pwd.yml logs create-site"; exit 1; }

echo "==> Site is ready."

echo "==> Copying uk.po into containers..."
for svc in backend queue-long queue-short scheduler; do
    docker compose -f pwd.yml cp "$UK_PO" \
        "$svc:/home/frappe/frappe-bench/apps/erpnext/erpnext/locale/uk.po"
done

echo "==> Enabling Ukrainian language..."
docker compose -f pwd.yml exec -T backend bench --site frontend console <<'PYTHON'
import frappe
if not frappe.db.exists("Language", "uk"):
    doc = frappe.get_doc({
        "doctype": "Language",
        "language_code": "uk",
        "language_name": "Українська",
        "enabled": 1,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    print("Ukrainian language enabled")
else:
    frappe.db.set_value("Language", "uk", "enabled", 1)
    frappe.db.commit()
    print("Ukrainian language already exists, ensured enabled")
PYTHON

echo "==> Clearing cache..."
docker compose -f pwd.yml exec -T backend bench --site frontend clear-cache

echo ""
echo "Done! ERPNext is running at http://localhost:8080"
echo "  Login: Administrator / admin"
echo ""
echo "  To use Ukrainian:"
echo "  1. Login -> Settings (gear icon) -> Language -> select 'Українська'"
echo "  2. Or set site-wide default:"
echo "     docker compose -f pwd.yml exec backend bench --site frontend set-config language uk"
