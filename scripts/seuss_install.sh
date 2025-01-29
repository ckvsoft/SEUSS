#!/bin/bash
# -*- coding: utf-8 -*-
#
# MIT License
#
# Copyright (c) 2024 Christian Kvasny chris(at)ckvsoft.at
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

# Color codes for better formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Read default values or values from environment variables
github_branch="${BRANCH:-main}"
github_url="${GITHUB_URL:-https://github.com/ckvsoft/SEUSS/archive/$github_branch.zip}"
target_directory="${TARGET_DIRECTORY:-/data/seuss}"
temp_directory="/tmp/seuss_temp"  # New temporary directory
backup_directory="${target_directory}_backup"  # Backup directory

# Function to restore specific files after an update
restore_files() {
    echo -e "${YELLOW}Restoring config files...${NC}"
    cp "$backup_directory/config.toml" "$target_directory/config.toml"
    cp "$backup_directory/logfiles/logfile.*" "$target_directory/"
}

# Function to create a backup of the existing installation
create_backup() {
    echo -e "${YELLOW}Creating backup of the existing installation...${NC}"
    mv "$target_directory" "$backup_directory"
}

# Function to prompt for the target directory
prompt_for_target_directory() {
    read -p "Enter the target directory (default: /data/seuss): " user_target_directory
    target_directory="${user_target_directory:-/data/seuss}"
}

# Determine if the script is running as an update
is_update=false
if [ "$1" == "update" ]; then
    is_update=true
fi

# Determine the package manager
if command -v apt-get &>/dev/null; then
    package_manager="apt-get"
elif command -v dnf &>/dev/null; then
    package_manager="dnf"
elif command -v opkg &>/dev/null; then
    package_manager="opkg"
else
    echo -e "${RED}No supported package manager (apt-get, dnf, opkg) found. Please install 'venv' and 'pip' manually.${NC}"
    exit 1
fi

# Check if the required tools are present
command -v unzip >/dev/null 2>&1 || { echo -e "${RED}The script requires 'unzip', but it is not installed. Please install it.${NC}"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo -e "${RED}The script requires 'python3', but it is not installed. Please install it.${NC}"; exit 1; }

# Install venv and pip using the determined package manager
if [ "$package_manager" == "opkg" ]; then
    echo -e "${GREEN}opkg found. Running opkg update...${NC}"
    opkg update
    echo -e "${GREEN}Installing pip...${NC}"
    $package_manager install python3-pip
else
    echo -e "${GREEN}Installing virtualenv and pip...${NC}"
    if [ "$(whoami)" == "root" ]; then
        $package_manager install -y python3-venv python3-pip
    else
        sudo $package_manager install -y python3-venv python3-pip
    fi
fi

if [ ! -d "$target_directory" ]; then
    create_backup
fi

# Check if the target directory already exists or create it
mkdir -p "$target_directory" 2>/dev/null
if [ $? -ne 0 ]; then
    # Prompt for the directory if creation fails
    prompt_for_target_directory
    mkdir -p "$target_directory" || { echo -e "${RED}Failed to create the target directory. Exiting.${NC}"; exit 1; }
fi

if [ "$is_update" == true ]; then
    restore_files
fi

# Step 1: Download and extract GitHub package to the temporary directory
echo -e "${GREEN}Step 1: Download and extract GitHub package${NC}"
mkdir -p "$temp_directory"

if command -v wget &>/dev/null; then
    wget -O "$temp_directory/downloaded.zip" "$github_url"
elif command -v curl &>/dev/null; then
    curl -L "$github_url" -o "$temp_directory/downloaded.zip"
else
    echo -e "${RED}Neither 'wget' nor 'curl' found. Please install one of the two tools and try again.${NC}"
    exit 1
fi

# Check if the download and extraction were successful
if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to download or extract the GitHub package. Exiting.${NC}"
    exit 1
fi

# Check if the download and extraction were successful

# Check if the download and extraction were successful
if ! unzip -o "$temp_directory/downloaded.zip" -d "$temp_directory" >/dev/null; then
    echo -e "${RED}Failed to extract the GitHub package. Exiting.${NC}"
    exit 1
fi

# Check if the extraction was successful
if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to extract the GitHub package. Exiting.${NC}"
    exit 1
fi

# Move contents to the target directory
cp -r "$temp_directory/SEUSS-$github_branch"/* "$target_directory"

# Clean up temporary files
rm -r "$temp_directory"
# rm "$temp_directory/downloaded.zip"

if [ "$package_manager" != "opkg" ]; then
    # Step 2: Create and activate the virtual environment
    echo -e "${GREEN}Step 2: Create and activate virtual environment${NC}"
    if [ "$is_update" != true ]; then
        python3 -m venv "$target_directory/venv"
    fi
    source "$target_directory/venv/bin/activate"
    # Step 3: Install dependencies
    echo -e "${GREEN}Step 3: Install dependencies${NC}"
    pip3 install --upgrade -r "$target_directory/requirements.txt"
else
    echo -e "${GREEN}Step 2: Install dependencies${NC}"
    /bin/bash "$target_directory/missing.sh"
    /bin/bash "$target_directory/install.sh"
fi

echo -e "${GREEN}Installation completed successfully.${NC}"
