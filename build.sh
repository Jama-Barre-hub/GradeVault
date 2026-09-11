#!/usr/bin/env bash
# Build step for the deployed service.
#
# Runs on every deploy, before the new version starts serving.

set -o errexit   # stop on the first failure
set -o nounset
set -o pipefail

echo "--> Installing production dependencies"
# requirements.txt only. Test and lint tools have no business on a
# production server: a smaller install is less to go wrong and less to
# keep patched.
pip install --no-cache-dir -r requirements.txt

echo "--> Collecting static files"
python manage.py collectstatic --no-input

echo "--> Applying database migrations"
python manage.py migrate --no-input

# Populate the public demo on its first deploy.
#
# `seed_demo` refuses to run when the demo school already exists, so
# every later deploy is a no-op and nothing a visitor did is wiped. It
# only ever touches its own demo institution, so this could not damage a
# real school's records even if DEMO_MODE were set by mistake.
#
# ${DEMO_MODE:-} rather than $DEMO_MODE because `set -o nounset` is on
# and the variable is absent in a normal deployment.
if [ "${DEMO_MODE:-}" = "True" ]; then
  echo "--> Seeding the public demo"
  python manage.py seed_demo --publish
fi

echo "--> Build complete"
