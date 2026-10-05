---
title: DocuMind API
emoji: 📄
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
short_description: Backend for DocuMind, a RAG document Q&A app (FastAPI)
---

# DocuMind API

FastAPI backend of [DocuMind](https://github.com/dtgdheerajkashyap-droid/documind): upload PDFs and
ask questions answered only from them, with page-level citations.

- Interactive API docs: `/docs`
- Health check: `/api/health`

This Space is deployed from the `backend/` folder of the GitHub repository by
`scripts/deploy_hf_space.py`. Configuration (database URL, Gemini key, CORS) is set as Space
secrets and variables.
