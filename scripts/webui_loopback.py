"""Development-only loopback transport to fixed WebUI/API services on Docker internal net.
Uses existing operator Docker CLI access. No socket or new network is given to agents.
No HTTP/body logging; byte streams include session data and are never printed.
"""

import argparse
import asyncio
import contextlib
import re

# Trusted fixed transport code, never model/source/request supplied executable text.
TUNNEL = r"""
import socket,sys,threading
sock=socket.create_connection(("127.0.0.1",PORT),5)
sock.settimeout(None)
def forward():
    try:
        while data:=sys.stdin.buffer.read1(65536):sock.sendall(data)
    except OSError:pass
    finally:
        try:sock.shutdown(socket.SHUT_WR)
        except OSError:pass
threading.Thread(target=forward,daemon=True).start()
try:
    while data:=sock.recv(65536):
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
finally:sock.close()
"""


async def serve(project, ui_port=8088, api_port=8000):
    if not re.fullmatch(r"caliburn-webui-[a-z0-9-]+", project):
        raise ValueError("Invalid smoke project")

    async def handle(reader, writer, service, port):
        process = None

        async def send_input():
            while data := await reader.read(65536):
                process.stdin.write(data)
                await process.stdin.drain()

        async def send_output():
            while data := await process.stdout.read(65536):
                writer.write(data)
                await writer.drain()

        tasks = []
        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                "--interactive",
                project + "-" + service + "-1",
                "python",
                "-u",
                "-c",
                TUNNEL.replace("PORT", str(port)),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            tasks = [asyncio.create_task(send_input()), asyncio.create_task(send_output())]
            async with asyncio.timeout(300):
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for item in done:
                    await item
        except (OSError, TimeoutError, ConnectionError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if process is not None:
                if process.stdin:
                    process.stdin.close()
                if process.returncode is None:
                    process.kill()
                await process.wait()
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    servers = []
    for local, service, remote in [(ui_port, "open-webui", 8080), (api_port, "caliburn-api", 8000)]:

        async def accept(reader, writer, target=service, port=remote):
            await handle(reader, writer, target, port)

        servers.append(await asyncio.start_server(accept, "127.0.0.1", local))
    print(f"Loopback smoke transport ready: WebUI {ui_port}, API {api_port}", flush=True)
    await asyncio.gather(*(server.serve_forever() for server in servers))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--project", default="caliburn-webui-verify")
    args = p.parse_args()
    asyncio.run(serve(args.project))


if __name__ == "__main__":
    main()
