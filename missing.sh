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
if [ -e "$REQUIREMENTS_FILE" ]; then
    current_modified_time=$(stat -c %Y "$REQUIREMENTS_FILE")
    last_modified_time=0

    # Check if the last modified file exists
    if [ -e "$LAST_MODIFIED_FILE" ]; then
        last_modified_time=$(cat "$LAST_MODIFIED_FILE")
    fi

    # Compare change times
    if [ "$current_modified_time" -gt "$last_modified_time" ]; then
        echo "requirements.txt has changed since the last call. Update the packages."

        # Update opkg
        if opkg update; then
            echo "opkg update completed successfully."
        else
            echo "Error: opkg update failed. Exiting."
            exit 1
        fi

        # Install python3-pip if not already installed
        if ! which pip3 &> /dev/null; then
            if opkg install python3-pip; then
                echo "python3-pip installed successfully."
            else
                echo "Error: Failed to install python3-pip. Exiting."
                exit 1
            fi
        fi

        all_packages_installed=true

        while IFS= read -r line; do
            # Ignorieren von Kommentaren und leeren Zeilen
            if [[ "$line" =~ ^[[:space:]]*# || -z "$line" ]]; then
                continue
            fi

            # Extract the package name before the version statement
            package_name=$(echo "$line" | awk -F '[=~><]' '{print $1}')

            # Check if the package is already installed
            if pip3 show "$package_name" &> /dev/null; then
                echo "Package $package_name is already installed."
            else
                # Installing the package with pip3
                if pip3 install "$line"; then
                    echo "Package $package_name installed successfully."
                else
                    echo "Error: Failed to install package $package_name. Exiting."
                    all_packages_installed=false
                    break
                fi
            fi

        done < "$REQUIREMENTS_FILE"

        if [ "$all_packages_installed" = true ]; then
            echo "$current_modified_time" > "$LAST_MODIFIED_FILE"
        else
            echo "Error: Not all packages were successfully installed."
            exit 1
        fi

        echo "Packages installation completed successfully."
    else
        echo "requirements.txt has not changed since the last time it was called. No update required."
    fi
else
    echo "Error: The requirements.txt file does not exist."
fi
