import json
import socket
from pathlib import Path

def request(command, socket_path=None):
    path=socket_path or Path(__file__).resolve().parent.parent/'.private/session.sock'
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
        sock.settimeout(180); sock.connect(str(path))
        sock.sendall(json.dumps(command,ensure_ascii=False).encode()+b'\n')
        parts=[]
        while True:
            part=sock.recv(1024*1024)
            if not part: break
            parts.append(part)
            if part.endswith(b'\n'): break
        response=json.loads(b''.join(parts))
        if not response['ok']: raise RuntimeError(response['error'])
        return response.get('data')
