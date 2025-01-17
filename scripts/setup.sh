#!/usr/bin/env bash
# Setups the repository.

set -e

# Stop on errors
cd "$(dirname "$0")/.."

# Add default vscode settings if not existing
#SETTINGS_FILE=./.vscode/settings.json
#SETTINGS_TEMPLATE_FILE=./.vscode/settings.default.json
#if [ ! -f "$SETTINGS_FILE" ]; then
#    echo "Copy $SETTINGS_TEMPLATE_FILE to $SETTINGS_FILE."
#    cp "$SETTINGS_TEMPLATE_FILE" "$SETTINGS_FILE"
#fi


mkdir -p config

if [ ! -n "$VIRTUAL_ENV" ]; then
  if [ -x "$(command -v uv)" ]; then
    uv venv venv
  else
    python3 -m venv venv
  fi
  source venv/bin/activate
fi

if ! [ -x "$(command -v uv)" ]; then
  python3 -m pip install uv
fi

# scripts/bootstrap.sh
#
pip install -r requirements_test.txt --upgrade
pip install -r requirements.txt --upgrade



# cd "$(dirname "$0")/.."
# Set the path to custom_components
## This let's us have the structure we want <root>/custom_components/volvo_cars
## while at the same time have Home Assistant configuration inside <root>/config
## without resulting to symlinks.
# export PYTHONPATH="${PYTHONPATH}:${PWD}/custom_components"

echo "trying hass"
hass --script ensure_config -c config


exit 0

pip install -r requirements.txt
pip install -r requirements-test.txt
pytest ./tests/ --cov=custom_components/volvo_cars --cov-report term-missing -vv
