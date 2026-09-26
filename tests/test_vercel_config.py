"""Regression checks for the root Vercel project configuration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.no_db
def test_vercel_config_builds_the_frontend_subdir_and_preserves_spa_routing():
    config = json.loads(Path("vercel.json").read_text())

    assert config["framework"] == "vite"
    assert config["installCommand"] == "cd frontend && npm ci --legacy-peer-deps"
    assert config["buildCommand"] == "cd frontend && npm run build"
    assert config["outputDirectory"] == "frontend/dist"
    assert config["rewrites"] == [
        {
            "source": "/((?!api(?:/|$)|.*\\..*).*)",
            "destination": "/index.html",
        }
    ]
