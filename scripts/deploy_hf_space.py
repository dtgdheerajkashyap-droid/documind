"""Deploy the backend to a Hugging Face Docker Space.

Reads secrets from `deploy.env` (HF_TOKEN, NEON_DATABASE_URL) and the Gemini key
from `.env`, creates/updates the Space `<user>/documind-api`, sets its secrets
and variables, and uploads the `backend/` folder. Hugging Face then builds the
Dockerfile and starts the container.

    backend/.venv/Scripts/python scripts/deploy_hf_space.py [--frontend-url https://...]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent.parent
SPACE_NAME = "documind-api"
IGNORE = [
    ".venv/*",
    "data/*",
    "tests/*",
    "**/__pycache__/*",
    ".pytest_cache/*",
    ".ruff_cache/*",
    ".env",
    "*.pyc",
]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def sqlalchemy_url(url: str) -> str:
    """Neon gives `postgresql://...`; SQLAlchemy needs the psycopg 3 driver name."""
    return re.sub(r"^postgres(ql)?://", "postgresql+psycopg://", url)


def space_host(repo_id: str) -> str:
    return "https://" + re.sub(r"[^a-z0-9-]", "-", repo_id.lower().replace("/", "-")) + ".hf.space"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-url", action="append", default=[], help="allowed CORS origin")
    args = parser.parse_args()

    secrets = read_env(ROOT / "deploy.env")
    app_env = read_env(ROOT / ".env")
    for key in ("HF_TOKEN", "NEON_DATABASE_URL"):
        if not secrets.get(key):
            raise SystemExit(f"{key} is missing in deploy.env")
    if not app_env.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY is missing in .env")

    api = HfApi(token=secrets["HF_TOKEN"])
    user = api.whoami()["name"]
    repo_id = f"{user}/{SPACE_NAME}"
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    print(f"Space: https://huggingface.co/spaces/{repo_id}")

    api.add_space_secret(repo_id, "DATABASE_URL", sqlalchemy_url(secrets["NEON_DATABASE_URL"]))
    api.add_space_secret(repo_id, "GEMINI_API_KEY", app_env["GEMINI_API_KEY"])
    origins = ["http://localhost:3000", *args.frontend_url]
    variables = {
        "CORS_ORIGINS": ",".join(origins),
        # Vercel production and preview URLs of the "documind" project.
        "CORS_ORIGIN_REGEX": r"https://documind(-[a-z0-9-]+)?\.vercel\.app",
        # Hugging Face's proxy appends the real client IP to X-Forwarded-For.
        "TRUSTED_PROXY_HOPS": "1",
        "LOG_FORMAT": "json",
        "GEMINI_MODEL": app_env.get("GEMINI_MODEL") or "gemini-flash-latest",
        "GEMINI_FALLBACK_MODELS": app_env.get("GEMINI_FALLBACK_MODELS")
        or "gemini-flash-lite-latest",
    }
    for key, value in variables.items():
        api.add_space_variable(repo_id, key, value)

    api.upload_folder(
        repo_id=repo_id,
        repo_type="space",
        folder_path=ROOT / "backend",
        ignore_patterns=IGNORE,
        commit_message="Deploy DocuMind backend",
    )
    api.upload_file(
        repo_id=repo_id,
        repo_type="space",
        path_or_fileobj=ROOT / "deploy" / "huggingface" / "README.md",
        path_in_repo="README.md",
        commit_message="Space README",
    )
    print(f"API URL: {space_host(repo_id)}")


if __name__ == "__main__":
    main()
