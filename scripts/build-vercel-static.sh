#!/usr/bin/env sh
set -eu

# Vercel ne reçoit que les ressources publiques du site, jamais le backend,
# les variables Neon, la base locale ni les pièces déposées par les candidats.
rm -rf dist
mkdir -p dist/assets dist/media
cp frontend/emsp.css frontend/emsp.js frontend/emsp-icon.png frontend/preview.webp dist/assets/
cp -R Photos/. dist/media/
