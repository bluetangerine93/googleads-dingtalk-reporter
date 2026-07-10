#!/bin/zsh
set -euo pipefail

cd /Users/jasmine/Documents/谷歌
mkdir -p logs data

if [ -d .venv ]; then
  source .venv/bin/activate
fi

python3 -m googleads_dingtalk "$@"
