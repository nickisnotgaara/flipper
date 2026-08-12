#!/usr/bin/env python3
"""Trivial static-file server for the Next.js export (out/).

Used in production via:
    docker run -d --name flipper_nextjs \\
        -p 3000:3000 \\
        --mount type=bind,source=/opt/flipper/web/next/out,target=/usr/share/nginx/html,readonly \\
        --mount type=bind,source=/opt/flipper/web/next/serve.py,target=/serve.py,readonly \\
        flipper-api:latest python3.11 /serve.py

Why not nginx? We could, but this stdlib-only version is dependency-free and
simpler to debug. The original choice was nginx-alpine; this Python fallback
exists for cases where pulling another image is inconvenient.
"""
import http.server
import os
import socketserver

os.chdir("/usr/share/nginx/html")


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_a, **_k):
        return  # silence default access log (docker logs has its own)

    def end_headers(self):
        # CORS for any cross-origin embed (e.g. embed in another Next.js app).
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


if __name__ == "__main__":
    with socketserver.TCPServer(("0.0.0.0", 3000), Handler) as httpd:
        print("serving on 3000", flush=True)
        httpd.serve_forever()
