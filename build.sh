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

echo "--> Build complete"
