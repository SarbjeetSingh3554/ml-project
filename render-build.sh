#!/usr/bin/env bash
# exit on error
set -o errexit

# Upgrade pip
pip install --upgrade pip

# Pre-compiled binaries try karne ke liye
pip install cmake
pip install dlib --prefer-binary

# Baki saari libraries
pip install -r requirements.txt