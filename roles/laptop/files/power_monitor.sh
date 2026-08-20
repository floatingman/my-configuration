#! /bin/bash
# Original stolen from Kobus van Schoor:
# https://kobusvs.co.za/blog/power-profile-switching/
#
# 2026-08-20: display policy added.
#   - Force AMD panel_power_savings (ABM / "Vari-Bright") to 0 in every state.
#     TuneD's "powersave" profile (pulled in by laptop-battery-powersave when
#     battery < LOW_BAT_PERCENT) sets it to 3, which dynamically reduces panel
#     backlight based on on-screen content over a few minutes -- perceived as
#     "brightness keeps dropping". Re-zero it after every profile switch.
#   - Backlight: near-max on AC, BAT_BRIGHT_PERCENT on battery. Applied only on
#     power-source/profile transitions so manual brightness tweaks are kept.
#   - AC is capped at AC_BRIGHT_PERCENT, not true max: this panel (Framework 16
#     amdgpu, kernel ~7.1.6+) has a bug where brightness at/near 100% drives the
#     panel DARKER. ~96% is the known-good top of the range. Proper fix is the
#     amdgpu.dcdebugmask=0x40000 kernel parameter.

BAT=$(echo /sys/class/power_supply/BAT*)
BAT_STATUS="$BAT/status"
BAT_CAP="$BAT/capacity"
AC_STATUS=/sys/class/power_supply/ACAD/online
LOW_BAT_PERCENT=70

AC_PROFILE="desktop"
BAT_PROFILE="balanced"
LOW_BAT_PROFILE="laptop-battery-powersave"

# --- display policy ---
AC_BRIGHT_PERCENT=96
BAT_BRIGHT_PERCENT=50
BL=$(echo /sys/class/backlight/*)
BL_MAX=$(cat "$BL/max_brightness")

kill_panel_abm() {
    # 0 disables content-adaptive backlight dimming on all amdgpu panels
    local pps
    for pps in /sys/class/drm/*/amdgpu/panel_power_savings; do
        [[ -e $pps ]] && echo 0 > "$pps" 2>/dev/null
    done
}

apply_display() {
    local level source
    if [[ $(cat "$AC_STATUS") == "1" ]]; then
        level=$(( BL_MAX * AC_BRIGHT_PERCENT / 100 ))
        source="AC"
    else
        level=$(( BL_MAX * BAT_BRIGHT_PERCENT / 100 ))
        source="battery"
    fi
    echo "$level" > "$BL/brightness"
    kill_panel_abm
    echo "setting brightness to $level/$BL_MAX ($source)"
}

# wait a while if needed
[[ -z $STARTUP_WAIT ]] || sleep "$STARTUP_WAIT"

# start the monitor loop
prev=$(tuned-adm active | tr -s ' ' | cut -d' ' -f4)
first=true

while true; do
    # read the current state
    if [[ $(cat "$AC_STATUS") == "0" ]]; then
        if [[ $(cat "$BAT_CAP") -gt $LOW_BAT_PERCENT ]]; then
            profile=$BAT_PROFILE
        else
            profile=$LOW_BAT_PROFILE
        fi
    else
        profile=$AC_PROFILE
    fi

    # set the new profile
    if [[ $prev != "$profile" ]]; then
        echo setting power profile to $profile
        # powerprofilesctl set $profile
        tuned-adm profile $profile
    fi

    # apply display policy on every transition (and once at startup); must run
    # after tuned-adm so any panel_power_savings the profile set gets zeroed
    if [[ $prev != "$profile" || $first == true ]]; then
        apply_display
        first=false
    fi

    prev=$profile

    sleep 10s
done
