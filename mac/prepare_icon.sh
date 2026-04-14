#!/bin/bash
#
# prepare_icon.sh
# Usage: ./prepare_icon.sh <path-to-source-image>
#
# Takes a source image (e.g. the ITW cartoon), crops the head area,
# and generates all AppIcon sizes + the Panel-Watermark asset.
#
# Requires: sips (preinstalled on macOS)
#
# The crop rectangle assumes the head is in the upper half of a
# 1024x1024 source image. Tweak CROP_* if your image has different
# proportions.

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <path-to-source-image>"
    echo "Example: $0 ~/Downloads/mario-itw.png"
    exit 1
fi

SRC="$1"
if [ ! -f "$SRC" ]; then
    echo "Error: source image not found: $SRC"
    exit 1
fi

ASSETS="$(dirname "$0")/Jarvis-Menubar/Assets.xcassets"
APPICON="$ASSETS/AppIcon.appiconset"
HEAD_ASSET="$ASSETS/jarvis-head.imageset"

mkdir -p "$APPICON" "$HEAD_ASSET"

# Work in a scratch dir
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Normalize source to 1024x1024
sips -z 1024 1024 "$SRC" --out "$TMP/src.png" >/dev/null

# Crop the head area (top-center square).
# For a 1024x1024 image with the head in the top third,
# we take a 600x600 square starting at x=212, y=40.
CROP_X=212
CROP_Y=40
CROP_SIZE=600
sips --cropToHeightWidth $CROP_SIZE $CROP_SIZE "$TMP/src.png" \
     --cropOffset $CROP_Y $CROP_X \
     --out "$TMP/head.png" >/dev/null 2>&1 || \
     sips -c $CROP_SIZE $CROP_SIZE "$TMP/src.png" --out "$TMP/head.png" >/dev/null

# App icon sizes (1x / 2x for each base size)
declare -a SIZES=(16 32 128 256 512)
for s in "${SIZES[@]}"; do
    double=$((s * 2))
    sips -z $s $s "$TMP/head.png" --out "$APPICON/icon_${s}x${s}.png" >/dev/null
    sips -z $double $double "$TMP/head.png" --out "$APPICON/icon_${s}x${s}@2x.png" >/dev/null
done

# Panel watermark: just the cropped head at a few resolutions
sips -z 400 400 "$TMP/head.png" --out "$HEAD_ASSET/jarvis-head.png" >/dev/null
sips -z 800 800 "$TMP/head.png" --out "$HEAD_ASSET/jarvis-head@2x.png" >/dev/null
sips -z 1200 1200 "$TMP/head.png" --out "$HEAD_ASSET/jarvis-head@3x.png" >/dev/null

echo "✓ Generated AppIcon in: $APPICON"
echo "✓ Generated jarvis-head watermark in: $HEAD_ASSET"
echo
echo "Falls der Kopf-Ausschnitt nicht passt, aendere CROP_X/Y/SIZE oben"
echo "und fuehre das Skript erneut aus."
