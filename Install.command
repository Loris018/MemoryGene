#!/bin/bash
# Finder launcher from the unpacked GitHub ZIP.
set -u
cd "$(dirname "$0")" || exit 1
bash ./install.sh
result=$?
if [ -t 0 ]; then
  read -r -p "按回车关闭 / Press Return to close. "
fi
exit "$result"
