"""A checkpoint cannot vouch for model bytes that no longer exist."""
import asyncio
import json

import httpx
import pytest

from services.segmented_download import segmented_download


@pytest.mark.parametrize('partial', [None, b'abc', b'abcdefgh'])
def test_completed_ranges_require_their_original_complete_partial(tmp_path, partial):
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
