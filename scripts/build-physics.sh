#!/bin/sh
set -eu

WULFRAM_SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WULFRAM_CORE_ROOT=$(CDPATH= cd -- "$WULFRAM_SCRIPT_DIR/.." && pwd)
WULFRAM_PYTHON=${WULFRAM_PYTHON:-python3}

cmake \
    -S "$WULFRAM_CORE_ROOT/physics" \
    -B "$WULFRAM_CORE_ROOT/build/physics-linux-x64" \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DWULFRAM_PHYSICS_BUILD_PYTHON=ON \
    -DWULFRAM_PHYSICS_BUILD_TESTS=OFF \
    -DPython3_EXECUTABLE="$WULFRAM_PYTHON"
cmake --build "$WULFRAM_CORE_ROOT/build/physics-linux-x64" --target WulframPhysicsPython
