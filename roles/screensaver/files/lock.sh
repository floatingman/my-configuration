#!/bin/sh

hash brightnessctl 2>/dev/null
if [ $? -eq 0 ]; then
	BRIGHTNESS=true
fi

if ! pidof betterlockscreen >/dev/null; then
	if [ "$BRIGHTNESS" = true ]; then
		brightnessctl --quiet --save
		brightnessctl --quiet set 10%
	fi
	betterlockscreen -l dim
	if [ "$BRIGHTNESS" = true ]; then
		brightnessctl --quiet --restore
	fi
fi
