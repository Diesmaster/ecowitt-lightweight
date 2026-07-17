#!/usr/bin/env python3

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


HOST = "0.0.0.0"
PORT = 8080
LOG_FILE = "weather_payloads.jsonl"


def simplify(values: dict[str, list[str]]) -> dict[str, str | list[str]]:
    result = {}

    for key, items in values.items():
        result[key] = items[0] if len(items) == 1 else items

    return result


class WeatherRequestHandler(BaseHTTPRequestHandler):
    def capture_request(self) -> None:
        parsed_url = urlparse(self.path)
        query_data = simplify(parse_qs(parsed_url.query, keep_blank_values=True))

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b""

        content_type = self.headers.get("Content-Type", "")
        body_data = None

        if raw_body:
            if "application/x-www-form-urlencoded" in content_type:
                body_data = simplify(
                    parse_qs(
                        raw_body.decode("utf-8", errors="replace"),
                        keep_blank_values=True,
                    )
                )
            elif "application/json" in content_type:
                try:
                    body_data = json.loads(raw_body)
                except json.JSONDecodeError:
                    body_data = raw_body.decode("utf-8", errors="replace")
            else:
                body_data = raw_body.decode("utf-8", errors="replace")

        captured = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "client_ip": self.client_address[0],
            "method": self.command,
            "path": parsed_url.path,
            "query": query_data,
            "headers": dict(self.headers),
            "body": body_data,
        }

        print("\n" + "=" * 70)
        print(json.dumps(captured, indent=2, ensure_ascii=False))
        print("=" * 70)

        with open(LOG_FILE, "a", encoding="utf-8") as file:
            file.write(json.dumps(captured, ensure_ascii=False) + "\n")

        response = b"success"

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def do_GET(self) -> None:
        self.capture_request()

    def do_POST(self) -> None:
        self.capture_request()

    def log_message(self, format_string: str, *args: object) -> None:
        print(
            f"{self.client_address[0]} "
            f"[{self.log_date_time_string()}] "
            f"{format_string % args}"
        )


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), WeatherRequestHandler)

    print(f"Listening on http://{HOST}:{PORT}")
    print(f"Payloads will also be saved to {LOG_FILE}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
