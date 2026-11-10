"""The camera view: ONVIF profile choice, and the H.264 copy starting and stopping with the viewer.

  uv run --no-project --with numpy --with soxr --with websockets --with aiohttp --with pytest --with pytest-asyncio \
      python -m pytest -q tests/test_camera.py
"""
import asyncio
import json

import pytest

from thinksmart_client import camera


PROFILES = b'''<Envelope><Body>
  <Profiles token="profile_1"><VideoEncoderConfiguration>
    <Encoding>H264</Encoding><Resolution><Width>2560</Width><Height>1440</Height></Resolution>
  </VideoEncoderConfiguration><AudioEncoderConfiguration><Encoding>G711</Encoding></AudioEncoderConfiguration></Profiles>
  <Profiles token="profile_2"><VideoEncoderConfiguration>
    <Encoding>H264</Encoding><Resolution><Width>640</Width><Height>360</Height></Resolution>
  </VideoEncoderConfiguration></Profiles>
</Body></Envelope>'''


def test_the_smaller_h264_profile_is_the_one_shown():
    assert camera.pick_profile(PROFILES) == 'profile_2'
    assert camera.media_xaddr(b'<Media><XAddr>http://cam:2020/onvif/service</XAddr></Media>') == \
        'http://cam:2020/onvif/service'
    assert camera.stream_uri(b'<Uri>rtsp://192.168.31.152:554/stream2</Uri>') == 'rtsp://192.168.31.152:554/stream2'


def test_a_camera_without_h264_is_refused():
    with pytest.raises(camera.CameraError):
        camera.pick_profile(b'<Profiles token="p"><Encoding>H265</Encoding><Width>640</Width><Height>360</Height></Profiles>')


def test_the_stream_address_carries_the_account_and_logs_do_not():
    uri = camera.with_auth('rtsp://192.168.31.152:554/stream2', 'admin', 'a b/c')
    assert uri == 'rtsp://admin:a%20b%2Fc@192.168.31.152:554/stream2'
    assert 'a b/c' not in camera.redact('ffmpeg failed on ' + uri)
    args = camera.ffmpeg_args(uri)
    assert args[args.index('-c:v') + 1] == 'mjpeg'
    assert 'tcp' in args and 'libx264' not in args
    assert not camera.configured({})
    assert camera.configured({'camera': {'host': '192.168.31.152'}})


class ChunkStream:
    def __init__(self, data):
        self.data, self.pos, self.done = data, 0, asyncio.Event()

    async def read(self, n):
        if self.pos < len(self.data):
            chunk = self.data[self.pos:self.pos + n]
            self.pos += len(chunk)
            return chunk
        await self.done.wait()
        return b''

    async def readline(self):
        await self.done.wait()
        return b''


class FakeProc:
    def __init__(self, data):
        self.stdout, self.stderr = ChunkStream(data), ChunkStream(b'')
        self.returncode = None

    def terminate(self):
        self.returncode = -15
        self.stdout.done.set()
        self.stderr.done.set()

    def kill(self):
        self.terminate()

    async def wait(self):
        return self.returncode


@pytest.mark.asyncio
async def test_the_model_can_open_and_close_the_picture():
    from thinksmart_client import mcp

    sent, poked = [], []

    class Client:
        def __init__(self, host):
            self.cfg = {'camera': {'host': host}}

        def show_camera(self, open_):
            return camera.show(self.cfg, lambda k, d: sent.append((k, d)), lambda: poked.append(1), open_)

    async def call(client, open_):
        reply = await mcp.handle({'id': 1, 'method': 'tools/call',
                                  'params': {'name': 'self.camera.set', 'arguments': {'open': open_}}}, client=client)
        return json.loads(reply['result']['content'][0]['text'])

    assert await call(Client('192.168.31.152'), True) == {'success': True, 'open': True}
    assert await call(Client('192.168.31.152'), False) == {'success': True, 'open': False}
    assert sent == [('camera', {'open': True}), ('camera', {'open': False})] and poked == [1]
    missing = await call(Client(''), True)
    assert missing['success'] is False and '摄像头' in missing['reason']


@pytest.mark.asyncio
async def test_the_picture_starts_with_the_viewer_and_stops_when_they_leave():
    proc = FakeProc(b'\xff\xd8\xff\xd9')
    watched = []

    async def resolve():
        return 'rtsp://cam/stream2'

    async def spawn(url):
        assert url == 'rtsp://cam/stream2'
        return proc

    relay = camera.Relay(watched.append, resolve, spawn)
    sub = await relay.open()
    assert await sub.queue.get() == b'\xff\xd8\xff\xd9'
    assert watched == [True] and proc.returncode is None
    await relay.close(sub)
    assert watched == [True, False] and proc.returncode is not None
    await relay.close(sub)   # the page can disconnect twice
    assert watched == [True, False]
