"""Lancement dev : `python run.py` depuis `backend/` (uvicorn + reload, port 8000)."""

import os
import sys

import uvicorn

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
