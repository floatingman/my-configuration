#!/bin/sh
case "$1" in
    post)
        # Wait a moment for ACPI to settle
        sleep 2
        # Find all I2C HID devices and rebind them
        for dev in /sys/bus/i2c/drivers/i2c_hid_acpi/*/; do
            name=$(basename "$dev")
            if [ "$name" != "*" ]; then
                echo "$name" > /sys/bus/i2c/drivers/i2c_hid_acpi/unbind 2>/dev/null
                sleep 1
                echo "$name" > /sys/bus/i2c/drivers/i2c_hid_acpi/bind 2>/dev/null
            fi
        done
        ;;
esac
