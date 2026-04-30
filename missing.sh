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
# Persistent cache: holds the mtime of requirements.txt as it was at
# the end of the last successful run. We must NOT put this in /tmp
# because Venus OS clears /tmp on every boot, which would force a
# full pip-index scan against every package on every reboot.
LAST_MODIFIED_FILE="/data/seuss/.last_pip_check"

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

# Fast path: if requirements.txt hasn't changed since the last
# successful check, all packages were already verified the last
# time and there's no point re-running pip index versions for
# every line (each takes 1-3 seconds against PyPI). Skip silently
# unless we're forced to run.
if [ "$current_modified_time" -eq "$last_modified_time" ]; then
    echo "Python packages already verified for current requirements.txt -- skipping."
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
check_succeeded=true

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
            check_succeeded=false
            exit 1
        fi
        continue
    fi

    # Case 2: package present -> check if a newer version is even available
    # before running the actual upgrade. `pip index versions` returns the
    # available versions on PyPI; we compare the highest one against what's
    # installed.
    printf "  %s: installed %s, checking PyPI..." "$package_name" "$installed_version"
    latest_version=$(pip3 index versions "$package_name" 2>/dev/null \
        | awk -F'[()]' '/Available versions:/ {split($0, a, "Available versions: "); split(a[2], b, ","); print b[1]}' \
        | tr -d ' ')

    if [ -z "$latest_version" ]; then
        # `pip index versions` not available on older pip, or network
        # hiccup. Fall back to the old "always upgrade" behaviour but
        # silently, and only mark as updated if pip actually says it
        # installed something.
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
        check_succeeded=false
        exit 1
    fi
done < "$REQUIREMENTS_FILE"

# Mark this requirements.txt mtime as fully verified, so the next
# run can take the fast path. Important: do this whether or not any
# package was actually upgraded -- "up-to-date" is just as much a
# successful verification as "upgraded". The only thing that resets
# the cache is the user touching requirements.txt or the script
# bailing out early on an error.
if [ "$check_succeeded" = true ]; then
    echo "$current_modified_time" > "$LAST_MODIFIED_FILE"
fi

if [ "$update_required" = true ]; then
    echo "Package updates completed."
else
    echo "All packages are already up-to-date."
fi
