#!/bin/sh
set -eu

uvicorn app.main:app --host 0.0.0.0 --port "${SERVICE_PORT}" &
pid=$!

python app/register_consul.py
wait "$pid"
