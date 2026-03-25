#!/bin/bash
echo "=== Installation Chromium ==="
python -m playwright install --with-deps chromium
echo "=== Démarrage des bots ==="
python onepiece_alert.py &
python pokemon_alert.py &
wait
