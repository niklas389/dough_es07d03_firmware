#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
# watch.sh - log the monitor's power state every few seconds on a diag-poke build.
#
#   MON=1 SPECCTL=./specctl tools/watch.sh [seconds] | tee watch.log
#
# Columns: time, 0x434 (panel supply: 0xF3 on / 0xE3 off), 0x426 (backlight
# enable: 0xFA on / 0xBA/0xAA off), 0x44B (LED supply: 0x0A on / 0x02 off),
# 0x3AA (PM51 state and wake status). "--" = no answer (deep standby or restart).
# Read-only; DDC over USB-B does not touch the DisplayPort link.
set -u
P=${POKE:-"$(dirname "$0")/poke.sh"}
INT=${1:-2}
rd() { "$P" read "$1" 2>/dev/null | sed -n 's/.*= \(0x[0-9A-Fa-f]*\)$/\1/p'; }
while :; do
    line="$(date +%T)"
    for r in 0x434 0x426 0x44B 0x3AA; do
        v=$(rd $r); line="$line  ${v:---}"
    done
    echo "$line"
    sleep "$INT"
done
