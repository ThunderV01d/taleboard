#!/bin/sh
# Copies the numba cache compiled at build time into writable /tmp (numba refuses a read-only cache dir), then hands over to Lambda's own entrypoint
cp -r /opt/numba-cache /tmp/numba-cache 2>/dev/null || true
exec /lambda-entrypoint.sh "$@"