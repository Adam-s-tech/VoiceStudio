"""A checkpoint cannot vouch for model bytes that no longer exist."""
import asyncio
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest


@pytest.mark.parametrize('partial', [None, b'abc', b'abcdefgh'])
def test_completed_ranges_require_their_original_complete_partial(tmp_path, partial):
    from services.segmented_download import segmented_download

    destination = tmp_path / 'model.bin'
    path = tmp_path / 'model.bin.part'
    if partial is not None:
        path.write_bytes(partial)
    (tmp_path / 'model.bin.part.done').write_text(json.dumps({'size': 8, 'done': [[0, 7]]}))
    fetched = []

    def origin(request):
        if request.method == 'HEAD':
            return httpx.Response(200, headers={'Content-Length': '8', 'Accept-Ranges': 'bytes'})
        fetched.append(request.headers['Range'])
        return httpx.Response(206, headers={'Content-Range': 'bytes 0-7/8'}, content=b'abcdefgh')

    async def download():
        async with httpx.AsyncClient(transport=httpx.MockTransport(origin)) as client:
            await segmented_download('https://model.example/file', str(destination), client=client)

    asyncio.run(download())
    assert destination.read_bytes() == b'abcdefgh'
    assert fetched == ([] if partial == b'abcdefgh' else ['bytes=0-7'])


@pytest.mark.parametrize('record', [[], {'size': 8, 'done': None}, {'size': 8, 'done': [False]}, {'size': 8, 'done': [[0, 7], [0, 'seven']]}])
def test_malformed_checkpoint_restarts_download(tmp_path, record):
    from services.segmented_download import segmented_download

    destination = tmp_path / 'model.bin'
    (tmp_path / 'model.bin.part').write_bytes(b'oldbytes')
    (tmp_path / 'model.bin.part.done').write_text(json.dumps(record))

    def origin(request):
        if request.method == 'HEAD':
            return httpx.Response(200, headers={'Content-Length': '8', 'Accept-Ranges': 'bytes'})
        return httpx.Response(206, headers={'Content-Range': 'bytes 0-7/8'}, content=b'newbytes')

    async def download():
        async with httpx.AsyncClient(transport=httpx.MockTransport(origin)) as client:
            await segmented_download('https://model.example/file', str(destination), client=client)

    asyncio.run(download())
    assert destination.read_bytes() == b'newbytes'


def test_oversized_partial_restarts_from_real_http_ranges(tmp_path):
    from services.segmented_download import segmented_download

    content = b'abcdefgh'
    destination = tmp_path / 'model.bin'
    destination.write_bytes(b'previous model')
    partial = tmp_path / 'model.bin.part'
    partial.write_bytes(content + b'old trailing bytes')
    checkpoint = tmp_path / 'model.bin.part.done'
    checkpoint.write_text(json.dumps({'size': len(content), 'done': [[0, 7]]}))
    fetched = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_HEAD(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()

        def do_GET(self):
            fetched.append(self.headers['Range'])
            self.send_response(206)
            self.send_header('Content-Range', 'bytes 0-7/8')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    async def download():
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            await segmented_download(
                f'http://127.0.0.1:{server.server_port}/model', str(destination),
                expected_etag=hashlib.sha256(content).hexdigest(), client=client,
            )

    try:
        asyncio.run(download())
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)

    assert fetched == ['bytes=0-7']
    assert destination.read_bytes() == content
    assert destination.stat().st_size == len(content)
    assert not partial.exists()
    assert not checkpoint.exists()
