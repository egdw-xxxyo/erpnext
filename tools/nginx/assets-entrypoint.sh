#!/bin/bash
# Start of the `assets` service: publish this release's files into the shared
# union (see publish_union.py), then serve the image's own asset tree.
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"

cp "$HERE/assets.conf" /etc/nginx/conf.d/frappe.conf

# Never a reason not to serve: the union is only the fallback for requests that
# name another release's files.
python3 "$HERE/publish_union.py" publish || echo "WARNING: publishing to the asset union failed"

exec nginx -g 'daemon off;'
