"""Deploy the backend to a free Render web service (Docker).

Reads secrets from `deploy.env` (RENDER_API_KEY, NEON_DATABASE_URL) and the Gemini key
from `.env`, then creates or updates the service `documind-api`, which Render builds
from `backend/Dockerfile` in the public GitHub repository. Push your commits first:
Render builds from the repository, not from this folder.

    backend/.venv/Scripts/python scripts/deploy_render.py [--frontend-url https://...] [--wait]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_hf_space import read_env, sqlalchemy_url

ROOT = Path(__file__).resolve().parent.parent
SERVICE_NAME = "documind-api"
REPO = "https://github.com/dtgdheerajkashyap-droid/documind"
# Same AWS region as the Neon database (us-east-2) to keep query latency low.
REGION = "ohio"
API = "https://api.render.com/v1"


def env_vars(secrets: dict[str, str], app_env: dict[str, str], origins: list[str]) -> list[dict]:
    values = {
        "DATABASE_URL": sqlalchemy_url(secrets["NEON_DATABASE_URL"]),
        "GEMINI_API_KEY": app_env["GEMINI_API_KEY"],
        "GEMINI_MODEL": app_env.get("GEMINI_MODEL") or "gemini-flash-latest",
        "GEMINI_FALLBACK_MODELS": app_env.get("GEMINI_FALLBACK_MODELS")
        or "gemini-flash-lite-latest",
        "ENVIRONMENT": "production",
        "LOG_FORMAT": "json",
        "CORS_ORIGINS": ",".join(origins),
        # Vercel production and preview URLs of the "documind" project.
        "CORS_ORIGIN_REGEX": r"https://documind(-[a-z0-9-]+)?\.vercel\.app",
        # Render's proxy appends the real client IP to X-Forwarded-For.
        "TRUSTED_PROXY_HOPS": "1",
        # The free instance has 512 MB of RAM and a fraction of a CPU: small
        # embedding batches keep peak memory under ~300 MB.
        "EMBEDDING_BATCH_SIZE": "8",
        "EMBEDDING_THREADS": "1",
    }
    return [{"key": k, "value": v} for k, v in values.items()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-url", action="append", default=[], help="allowed CORS origin")
    parser.add_argument("--wait", action="store_true", help="wait for the deploy to go live")
    args = parser.parse_args()

    secrets = read_env(ROOT / "deploy.env")
    app_env = read_env(ROOT / ".env")
    for key in ("RENDER_API_KEY", "NEON_DATABASE_URL"):
        if not secrets.get(key):
            raise SystemExit(f"{key} is missing in deploy.env")
    if not app_env.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY is missing in .env")

    client = httpx.Client(
        base_url=API,
        headers={"Authorization": f"Bearer {secrets['RENDER_API_KEY']}"},
        timeout=60,
    )

    def call(method: str, path: str, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.is_error:
            raise SystemExit(f"Render API {method} {path}: {response.status_code} {response.text}")
        return response.json() if response.content else None

    owner_id = call("GET", "/owners")[0]["owner"]["id"]
    variables = env_vars(secrets, app_env, ["http://localhost:3000", *args.frontend_url])
    existing = call("GET", "/services", params={"name": SERVICE_NAME, "ownerId": owner_id})

    if existing:
        service = existing[0]["service"]
        call("PUT", f"/services/{service['id']}/env-vars", json=variables)
        call("POST", f"/services/{service['id']}/deploys", json={})
        print(f"Updated service {service['id']} and started a deploy")
    else:
        created = call(
            "POST",
            "/services",
            json={
                "type": "web_service",
                "name": SERVICE_NAME,
                "ownerId": owner_id,
                "repo": REPO,
                "branch": "main",
                "rootDir": "backend",
                "autoDeploy": "yes",
                "envVars": variables,
                "serviceDetails": {
                    "runtime": "docker",
                    "plan": "free",
                    "region": REGION,
                    "healthCheckPath": "/api/health",
                    "envSpecificDetails": {
                        "dockerContext": ".",
                        "dockerfilePath": "./Dockerfile",
                    },
                },
            },
        )
        service = created["service"]
        print(f"Created service {service['id']}")

    print(f"Dashboard: {service['dashboardUrl']}")
    print(f"API URL: {service['serviceDetails']['url']}")

    if args.wait:
        status = None
        while status not in {"live", "build_failed", "update_failed", "canceled", "deactivated"}:
            time.sleep(15)
            deploy = call("GET", f"/services/{service['id']}/deploys", params={"limit": 1})[0]
            if deploy["deploy"]["status"] != status:
                status = deploy["deploy"]["status"]
                print(f"Deploy status: {status}", flush=True)
        if status != "live":
            raise SystemExit(f"Deploy ended with status {status}")


if __name__ == "__main__":
    main()
