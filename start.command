#!/bin/zsh
cd "${0:A:h}"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python -m uvicorn reader.app:app --host 127.0.0.1 --port 8765
else
  exec python3 -m uvicorn reader.app:app --host 127.0.0.1 --port 8765
fi
