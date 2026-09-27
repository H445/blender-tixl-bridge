"""Optional local JSON-lines client for TiXL's opt-in debug server."""
import json
import socket
import time


def exchange(method: str, port: int, timeout: float = 120, **params):
    """Preserve protocol envelopes and wire evidence for diagnostic clients."""
    request = {"id": str(time.time_ns()), "method": method, **params}
    request_line = json.dumps(request) + "\n"
    with socket.create_connection(("127.0.0.1", port), timeout=min(3, timeout)) as connection:
        connection.settimeout(timeout)
        connection.sendall(request_line.encode("utf-8"))
        line = connection.makefile("r", encoding="utf-8").readline()
    if not line:
        raise ConnectionError("TiXL debug bridge closed without a response")
    response = json.loads(line)
    return {"request": request, "response": response,
            "requestLine": request_line, "responseLine": line}


def call(method: str, port: int, timeout: float = 120, **params):
    response = exchange(method, port, timeout, **params)["response"]
    if not response.get("ok"):
        raise RuntimeError(json.dumps(response))
    return response.get("result")
