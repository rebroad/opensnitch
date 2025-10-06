#!/bin/bash

# OpenSnitch UI Launcher
# This script starts the OpenSnitch UI from the source directory

cd /home/rebroad/src/opensnitch/ui

# Activate virtual environment
source venv/bin/activate

# Start the UI
python bin/opensnitch-ui --socket unix:///tmp/osui.sock --background

echo "OpenSnitch UI started!"
