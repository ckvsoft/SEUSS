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

while IFS= read -r line; do
    # Ignore comments and empty lines
    if [[ "$line" =~ ^[[:space:]]*# || -z "$line" ]]; then
        continue
    fi

    # Extract package name
    package_name=$(echo "$line" | awk -F '[=~><]' '{print $1}')

    # Get installed version (if any)
    installed_version=$(pip3 show "$package_name" | awk '/Version:/ {print $2}')

    # If package is not installed, install it
    if [ -z "$installed_version" ]; then
        echo "Installing $package_name..."
        if pip3 install "$line"; then
            echo "$package_name installed successfully."
            update_required=true
        else
            echo "Error: Failed to install $package_name."
            exit 1
        fi
    else
        # Update the package if a newer version is available
        echo "Checking for newer version of $package_name..."

        # Attempt to install the latest version
        if pip3 install --upgrade "$package_name"; then
            echo "$package_name updated successfully."
            update_required=true
        else
            echo "Error: Failed to update $package_name."
            exit 1
        fi
    fi
done < "$REQUIREMENTS_FILE"

# Only update timestamp if at least one package was updated
if [ "$update_required" = true ]; then
    echo "$current_modified_time" > "$LAST_MODIFIED_FILE"
    echo "Package updates completed."
else
    echo "All packages are already up-to-date."
fi
