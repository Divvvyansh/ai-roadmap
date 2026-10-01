"""Week 1, Step 3 — talk to server.py over stdio with no SDK at all.

Run:  .venv/bin/python raw_client.py
"""

import json
import subprocess
import sys

PROTOCOL_VERSION = "2026-07-28"


def start_server() -> subprocess.Popen:
    """Launch server.py as a subprocess with pipes on stdin/stdout."""
    return subprocess.Popen(
        [sys.executable, "server.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,          
        text=True,
        bufsize=1,            # line buffered on '/n' — without this you can deadlock
    )


def send(proc: subprocess.Popen, message: dict) -> None:
    """Write one JSON object followed by a newline, and flush."""
    line = json.dumps(message)
    print(f"--> {line}")
    proc.stdin.write(line + "\n")
    proc.stdin.flush()


def read(proc: subprocess.Popen) -> dict:
    """Read one line from the server and parse it."""
    out = proc.stdout.readline()
    if out == "":
        print("Server died unexpectedly.")
        sys.exit(1)
    decoded = json.loads(out)
    print(f"<-- {decoded}")
    return decoded


def main() -> None:
    proc = start_server()

    message = {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
         "protocolVersion": PROTOCOL_VERSION,
         "capabilities": {},
         "clientInfo": {"name":"raw-client","version":"0.1"}}}
    
    send(proc, message)
    response = read(proc)

    # Q: in "capabilities" the server sends back, what did it say it has?
    #    Your server declares no resources or prompts yet. Is the key absent,
    #    or present and empty? Those mean different things to a client.
    # A: The server still advertises prompts and resources, but it has no prompts or resources yet. The key is present and empty.

    message_2 = {"jsonrpc":"2.0","method":"notifications/initialized"}
    send(proc, message_2)

    # Do NOT call read() after this one. Q: what happens to your client if you do?
    # A: If you call read() after sending the "notifications/initialized" message,
    #    your client will block indefinitely waiting for a response that will never come,
    #    since notifications do not expect a response. This will cause your client to hang.

    message_3 = {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
    send(proc, message_3)
    response_3 = read(proc)
    input_schema = response_3["result"]["tools"][0]["inputSchema"]

    message_4 = {"jsonrpc":"2.0","id":3,"method":"tools/call",
       "params":{"name":"run_query","arguments":{"sql":"SELECT * FROM Artist LIMIT 3"}}}
    send(proc, message_4)
    response_4 = read(proc)

    message_5 = {"jsonrpc":"2.0","id":4,"method":"tools/call",
           "params":{"name":"does_not_exist","arguments":{"sql":"SELECT * FROM Artist LIMIT 3"}}}
    send(proc, message_5)
    response_5 = read(proc)

    message_6 = {"jsonrpc":"2.0","id":5,"method":"tools/call",
           "params":{"name":"run_query","arguments":{"sql":"SELECT nope FROM Album"}}}
    send(proc, message_6)
    response_6 = read(proc)

    # One response has a top-level "error" key. The other has "result" with
    # isError: true. Which is which, and why does the protocol separate them?
    # Hint: which of these two is a bug the MODEL can fix by trying again?
    # A: The first one is an iss_error=true because a unknown tool call is still a successful RPC response.
    # On the other hand, the second one has no error flag or iss_error becuase to get an error you must break the protocol itself.
    # For ex: try method:"tool/nope".

    proc.terminate()

if __name__ == "__main__":
    main()
