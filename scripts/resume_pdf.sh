#!/usr/bin/env bash
# Render resume.md -> personal/resume.pdf (the file the driver attaches).
SECONDS=0
.venv/bin/python scripts/resume_render.py
duration=$SECONDS
echo "Took $((duration / 60)):$((duration % 60))"
