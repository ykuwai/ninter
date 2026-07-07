#!/usr/bin/env python3
"""Serve the project over HTTP and open the Ninter previewer.

Fonts must be loaded over http:// (browsers block local font files on file://),
so this starts a tiny static server rooted at the project and opens the page.
"""
import http.server
import os
import socketserver
import threading
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8753


def main() -> None:
    os.chdir(ROOT)
    handler = http.server.SimpleHTTPRequestHandler
    # allow reuse so restarts don't hit "address in use"
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), handler) as httpd:
        url = f"http://127.0.0.1:{PORT}/preview/index.html"
        print(f"Ninter previewer -> {url}")
        print("Press Ctrl+C to stop.")
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")


if __name__ == "__main__":
    main()
