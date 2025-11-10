#!/usr/bin/env python3
"""
Simple startup script for the Multi-tenant RAG service.
Runs on port 8000 by default for easy deployment.
"""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    host = os.getenv("HOST", "127.0.0.1")
    reload = os.getenv("RELOAD", "true").lower() == "true"

    print(f"Starting Multi-tenant RAG Service on {host}:{port}")
    print(f"Reload: {'enabled' if reload else 'disabled'}")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload
    )
