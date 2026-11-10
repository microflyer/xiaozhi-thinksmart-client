"""Live view of one ONVIF camera on the kiosk page.

The page cannot open RTSP, and this WebKit build cannot play H.264 through Media Source
Extensions (it has no h264parse). ONVIF tells us the smaller stream — this screen is 1280×800,
and the main stream is far larger than the kiosk should decode while it is also listening —
and ffmpeg turns that into JPEG frames the page draws. The camera here advertises H.264 and
sends HEVC; JPEG does not care. The stream runs only while the picture is open, which keeps
the screen on (device.Screen.watch) without disturbing a conversation's own hold.
"""
import asyncio
import base64
import hashlib
import logging
import re
import secrets
import shutil
import time
from urllib.parse import quote, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import aiohttp

log = logging.getLogger(__name__)

INIT_TIMEOUT = 12
_USERINFO = re.compile(r'://[^\s/]*@')


class CameraError(Exception):
    """Shown on the camera layer. Never carries the password or the stream address."""


def configured(cfg):
    return bool(str((cfg.get('camera') or {}).get('host') or '').strip())


def show(cfg, publish, poke, open_):
    """Ask the page to show or hide the picture. poke wakes a blank screen on open."""
    if not configured(cfg):
        return {'success': False, 'reason': '这台设备没有设置摄像头'}
    publish('camera', {'open': bool(open_)})
    if open_:
        poke()
    log.info('camera view: %s', 'open' if open_ else 'close')
    return {'success': True, 'open': bool(open_)}


def settings(cfg):
    cam = cfg.get('camera') or {}
    host = str(cam.get('host') or '').strip()
    if not host:
        raise CameraError('还没有设置摄像头')
    try:
        port = int(cam.get('onvif_port') or 80)
    except (TypeError, ValueError):
        port = 80
    if port < 1 or port > 65535:
        port = 80
    return host, port, str(cam.get('user') or ''), str(cam.get('password') or '')


def redact(text):
    return _USERINFO.sub('://', text)


def ffmpeg_args(url):
    # 20 fps at this size is a small slice of one core, and only while someone is watching
    return ['-hide_banner', '-loglevel', 'error', '-nostdin',
            '-rtsp_transport', 'tcp', '-i', url, '-an', '-vf', 'fps=20',
            '-c:v', 'mjpeg', '-q:v', '5', '-f', 'image2pipe', 'pipe:1']


def with_auth(uri, user, password):
    parts = urlsplit(uri)
    host = parts.hostname or ''
    if ':' in host and not host.startswith('['):
        host = f'[{host}]'
    netloc = f'{quote(user, safe="")}:{quote(password, safe="")}@{host}'
    if parts.port:
        netloc += f':{parts.port}'
    return urlunsplit((parts.scheme or 'rtsp', netloc, parts.path, parts.query, ''))


def _local(el):
    return el.tag.rsplit('}', 1)[-1]


def _xml(payload):
    try:
        return ET.fromstring(payload)
    except ET.ParseError:
        raise CameraError('摄像头返回的数据无法识别') from None


def raise_if_fault(payload):
    root = _xml(payload)
    if not any(_local(el) == 'Fault' for el in root.iter()):
        return
    texts = [el.text.strip() for el in root.iter() if _local(el) == 'Text' and el.text and el.text.strip()]
    raise CameraError(texts[-1] if texts else '摄像头拒绝了这次请求')


def media_xaddr(payload):
    root = _xml(payload)
    for el in root.iter():
        if _local(el) != 'Media':
            continue
        for child in list(el):
            if _local(child) == 'XAddr' and child.text and child.text.strip():
                return child.text.strip()
    raise CameraError('摄像头没有 ONVIF 媒体服务')


def pick_profile(payload):
    """The smallest H.264 profile token. Audio encodings have no width, so they are ignored."""
    root = _xml(payload)
    choices = []
    for el in root.iter():
        if _local(el) != 'Profiles':
            continue
        token, encoding, video, width, height = el.attrib.get('token'), None, None, None, None
        for child in el.iter():
            tag, text = _local(child), (child.text or '').strip()
            if tag == 'Encoding' and text:
                encoding = text
            elif tag == 'Width' and text.isdigit():
                width, video = int(text), encoding
            elif tag == 'Height' and text.isdigit():
                height = int(text)
        if token and video and video.upper() == 'H264' and width and height:
            choices.append((width * height, token))
    if not choices:
        raise CameraError('摄像头没有 H.264 画面')
    choices.sort()
    return choices[0][1]


def stream_uri(payload):
    root = _xml(payload)
    for el in root.iter():
        if _local(el) == 'Uri' and el.text and el.text.strip().lower().startswith('rtsp://'):
            return el.text.strip()
    raise CameraError('摄像头没有返回画面地址')


def _xml_text(value):
    return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _envelope(user, password, body):
    nonce = secrets.token_bytes(16)
    created = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
  <s:Header><wsse:Security s:mustUnderstand="1"><wsse:UsernameToken>
    <wsse:Username>{_xml_text(user)}</wsse:Username>
    <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</wsse:Password>
    <wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</wsse:Nonce>
    <wsu:Created>{created}</wsu:Created>
  </wsse:UsernameToken></wsse:Security></s:Header>
  <s:Body>{body}</s:Body></s:Envelope>'''


def _stream_body(token):
    return f'''<GetStreamUri xmlns="http://www.onvif.org/ver10/media/wsdl"><StreamSetup>
      <Stream xmlns="http://www.onvif.org/ver10/schema">RTP-Unicast</Stream>
      <Transport xmlns="http://www.onvif.org/ver10/schema"><Protocol>RTSP</Protocol></Transport>
    </StreamSetup><ProfileToken>{_xml_text(token)}</ProfileToken></GetStreamUri>'''


async def _soap(session, url, user, password, body):
    try:
        async with session.post(url, data=_envelope(user, password, body).encode(),
                                headers={'Content-Type': 'application/soap+xml; charset=utf-8'}) as resp:
            payload = await resp.read()
            if resp.status >= 400:
                raise CameraError('连不上摄像头')
    except (aiohttp.ClientError, TimeoutError):
        raise CameraError('连不上摄像头') from None
    raise_if_fault(payload)
    return payload


async def stream_url(host, port, user, password):
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
        device = f'http://{host}:{port}/onvif/device_service'
        caps = await _soap(session, device, user, password,
                           '<GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl"><Category>All</Category></GetCapabilities>')
        media = media_xaddr(caps)
        profiles = await _soap(session, media, user, password, '<GetProfiles xmlns="http://www.onvif.org/ver10/media/wsdl"/>')
        token = pick_profile(profiles)
        found = await _soap(session, media, user, password, _stream_body(token))
    return with_auth(stream_uri(found), user, password)


async def resolve(cfg):
    host, port, user, password = settings(cfg)
    return await stream_url(host, port, user, password)


async def spawn_ffmpeg(url):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise CameraError('这台设备没有 ffmpeg，播不了摄像头')
    return await asyncio.create_subprocess_exec(
        ffmpeg, *ffmpeg_args(url), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)


def _stop(proc):
    if proc is not None and proc.returncode is None:
        proc.terminate()


class _Viewer:
    def __init__(self):
        self.queue = asyncio.Queue(maxsize=4)
        self.ready = asyncio.Event()
        self.failed = None


class Relay:
    """One ffmpeg for every open viewer. The last one to leave stops it."""

    def __init__(self, on_watch, resolve_url, spawn=None):
        self.on_watch = on_watch
        self.resolve_url = resolve_url
        self.spawn = spawn or spawn_ffmpeg
        self.subs = []
        self.proc = self.task = self.err_task = None
        self.opening = None
        self.live = False
        self.lock = asyncio.Lock()

    async def _send(self, data):
        for sub in list(self.subs):
            if data is None:
                while sub.queue.full():
                    try:
                        sub.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                try:
                    sub.queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass
            else:
                await sub.queue.put(data)

    async def open(self):
        url = await self.resolve_url()
        async with self.lock:
            sub = _Viewer()
            self.subs.append(sub)
            first = len(self.subs) == 1
            if first:
                self.opening = sub
                self.on_watch(True)
            elif self.live:
                sub.ready.set()
        if not first:
            return await self._wait(sub)
        proc = err = None
        try:
            proc = await self.spawn(url)
        except CameraError as e:
            await self._fail(str(e))
            raise
        except Exception:
            await self._fail('连不上摄像头')
            raise CameraError('连不上摄像头') from None
        err = asyncio.create_task(self._drain(proc.stderr))
        async with self.lock:
            abandoned = self.opening is not sub
            if not abandoned:
                self.opening = None
                self.proc, self.err_task = proc, err
                self.task = asyncio.create_task(self._pump(proc))
        if abandoned:
            await self._shutdown(proc, None, err)
            raise CameraError('摄像头断开了')
        return await self._wait(sub)

    async def _wait(self, sub):
        try:
            await asyncio.wait_for(sub.ready.wait(), INIT_TIMEOUT)
        except asyncio.TimeoutError:
            await self.close(sub)
            raise CameraError('摄像头没有画面') from None
        if sub.failed:
            await self.close(sub)
            raise CameraError(sub.failed)
        return sub

    async def _fail(self, message):
        async with self.lock:
            subs, self.subs = list(self.subs), []
            self.opening = None
            self.live = False
            proc, task, err = self.proc, self.task, self.err_task
            self.proc = self.task = self.err_task = None
            self.on_watch(False)
        for sub in subs:
            sub.failed = message
            sub.ready.set()
        if proc or task or err:
            await self._shutdown(proc, task, err)

    async def close(self, sub):
        async with self.lock:
            if sub not in self.subs and self.opening is not sub:
                return
            if sub in self.subs:
                self.subs.remove(sub)
            if self.opening is sub:
                self.opening = None
            if self.subs or self.opening is not None:
                return
            proc, task, err = self.proc, self.task, self.err_task
            self.proc = self.task = self.err_task = None
            self.live = False
            self.on_watch(False)
        await self._shutdown(proc, task, err)

    async def _shutdown(self, proc, task, err):
        _stop(proc)
        for item in (task, err):
            if item is None:
                continue
            item.cancel()
            try:
                await item
            except asyncio.CancelledError:
                pass
        if proc is not None and proc.returncode is None:
            proc.kill()
            try:
                await proc.wait()
            except (ProcessLookupError, OSError):
                pass

    async def _drain(self, stream):
        if stream is None:
            return
        try:
            while True:
                line = await stream.readline()
                if not line:
                    return
                text = redact(line.decode('utf-8', 'replace')).strip()
                if text:
                    log.warning('camera: %s', text)
        except asyncio.CancelledError:
            raise

    async def _pump(self, proc):
        try:
            while self.proc is proc:
                chunk = await proc.stdout.read(32768)
                if not chunk:
                    break
                await self._send(chunk)
                if not self.live:
                    async with self.lock:
                        if self.proc is proc:
                            self.live = True
                            for sub in self.subs:
                                sub.ready.set()
            await self._end(proc, '摄像头断开了')
        except asyncio.CancelledError:
            raise

    async def _end(self, proc, message):
        async with self.lock:
            if self.proc is not proc:
                return
            self.proc = None
            self.live = False
            subs, self.subs = list(self.subs), []
            self.on_watch(False)
        for sub in subs:
            sub.failed = sub.failed or message
            sub.ready.set()
            while sub.queue.full():
                try:
                    sub.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            try:
                sub.queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        _stop(proc)
