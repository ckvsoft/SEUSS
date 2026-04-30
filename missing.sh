#!/bin/bash
#
# -*- coding: utf-8 -*-
#
# MIT License
#
# Copyright (c) 2024-2024 Christian Kvasny chris(at)ckvsoft.at
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
# Project: [SEUSS -> Smart Ess Unit Spotmarket Switcher
#
#

# Path to the requirements.txt file
REQUIREMENTS_FILE="/data/seuss/requirements.txt"
LAST_MODIFIED_FILE="/tmp/seuss_last_modified"

# Check if the requirements.txt file exists
if [ ! -e "$REQUIREMENTS_FILE" ]; then
    echo "Error: The requirements.txt file does not exist."
    exit 1
fi

current_modified_time=$(stat -c %Y "$REQUIREMENTS_FILE")
last_modified_time=0

# Check if the last modified file exists
if [ -e "$LAST_MODIFIED_FILE" ]; then
    last_modified_time=$(cat "$LAST_MODIFIED_FILE")
fi

# If the file has not changed since the last check, exit
if [ "$current_modified_time" -eq "$last_modified_time" ]; then
    echo "No changes detected in $REQUIREMENTS_FILE. Skipping package update."
    exit 0
fi

# Always update OPKG before installing packages
echo "Updating opkg..."
if opkg update; then
    echo "opkg update completed successfully."
else
    echo "Error: opkg update failed. Exiting."
    exit 1
fi

# Ensure python3-pip is installed
if ! which pip3 &> /dev/null; then
    echo "Installing python3-pip..."
    if opkg install python3-pip; then
        echo "python3-pip installed successfully."
    else
        echo "Error: Failed to install python3-pip. Exiting."
        exit 1
    fi
fi

update_required=false

echo "Checking Python packages against $REQUIREMENTS_FILE..."

while IFS= read -r line; do
    # Ignore comments and empty lines
    if [[ "$line" =~ ^[[:space:]]*# || -z "$line" ]]; then
        continue
    fi

    # Extract package name (strip any version pin like pkg==1.2 or pkg>=1.0)
    package_name=$(echo "$line" | awk -F '[=~><]' '{print $1}')

    # Get installed version (if any)
    installed_version=$(pip3 show "$package_name" 2>/dev/null | awk '/^Version:/ {print $2}')

    # Case 1: package missing -> install it
    if [ -z "$installed_version" ]; then
        echo "  $package_name: not installed -> installing..."
        if pip3 install "$line"; then
            echo "  $package_name: installed."
            update_required=true
        else
            echo "  $package_name: install FAILED."
            exit 1
        fi
        continue
    fi

    # Case 2: package present -> check if a newer version is even available
    # before running the actual upgrade. `pip index versions` returns the
    # available versions on PyPI; we compare the highest one against what's
    # installed. This avoids the noisy "Requirement already satisfied"
    # output for every package on every run, and -- more importantly --
    # avoids touching the LAST_MODIFIED timestamp when nothing changed.
    printf "  %s: installed %s, checking PyPI..." "$package_name" "$installed_version"
    latest_version=$(pip3 index versions "$package_name" 2>/dev/null \
        | awk -F'[()]' '/Available versions:/ {split($0, a, "Available versions: "); split(a[2], b, ","); print b[1]}' \
        | tr -d ' ')

    if [ -z "$latest_version" ]; then
        # `pip index versions` not available on older pip, or network
        # hiccup. Fall back to the old "always upgrade" behaviour but
        # silently, and only mark as updated if pip actually says it
        # installed something (return code is unfortunately 0 in both
        # cases, so we look at the output).
        upgrade_output=$(pip3 install --upgrade "$package_name" 2>&1)
        if echo "$upgrade_output" | grep -q "Successfully installed"; then
            echo " updated."
            update_required=true
        else
            echo " up-to-date."
        fi
        continue
    fi

    if [ "$installed_version" = "$latest_version" ]; then
        echo " up-to-date."
        continue
    fi

    echo " updating to $latest_version..."
    if pip3 install --upgrade "$package_name"; then
        echo "  $package_name: updated."
        update_required=true
    else
        echo "  $package_name: update FAILED."
        exit 1
    fi
done < "$REQUIREMENTS_FILE"

# Only update timestamp if at least one package was updated
if [ "$update_required" = true ]; then
    echo "$current_modified_time" > "$LAST_MODIFIED_FILE"
    echo "Package updates completed."
else
    echo "All packages are already up-to-date."
fi
