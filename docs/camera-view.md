# 摄像头实时画面

首页有一个摄像头按钮。点它，画面盖住主页；点关闭，回到原来的主页。唤醒后说「打开摄像头」「看监控」或「关掉监控」，模型用设备工具做同样的事。

这台设备是 ThinkSmart（`192.168.31.211`），摄像头是 TP-Link TL-IPC642XP-A4（`192.168.31.152`）。页面跑在设备上的 WebKitGTK 2.52 里，只访问 `127.0.0.1:8090`。

## 为什么是现在这样

摄像头说 ONVIF。ONVIF 只负责告诉客户端「画面在哪」，画面本身是 RTSP。浏览器打不开 RTSP。

这台摄像头的 ONVIF 档案写着两路都是 H.264：

| 档案 | 地址 | 实际码流 |
| --- | --- | --- |
| `profile_1` 主码流 | `rtsp://192.168.31.152:554/stream1` | HEVC，2560×1440，25 帧 |
| `profile_2` 子码流 | `rtsp://192.168.31.152:554/stream2` | HEVC，640×360，25 帧 |

客户端选像素更少的那一路。屏幕界面按 1280×800 画，主码流太大，解码时会和唤醒、回声消除抢这台 8 核 A53。

一开始把 H.264 原样封装成 MP4，交给页面的 Media Source Extensions 播。桌面浏览器可以。这块 WebKit 不行：`MediaSource.isTypeSupported` 对所有 `avc1` 都是 false，`addSourceBuffer` 直接拒绝。系统里没有 GStreamer 的 `h264parse`（`gstreamer1.0-plugins-bad` 没装）。所以页面改成自己收 JPEG，画到一张图上。摄像头实际发的是 HEVC 也没关系，ffmpeg 先解码再收成 JPEG。

## 架构

```
按钮或语音
    │
    ▼
页面  openCamera / closeCamera          模型  self.camera.set {open}
    │                                      │
    │  GET /api/camera/live                │  MCP tools/call
    ▼                                      ▼
web.py  camera_live                    mcp.py → Client.show_camera
    │                                      │
    │                                      │  事件 camera {open}
    │                                      └──────────► 页面（同一条 SSE）
    ▼
camera.Relay
    │  ONVIF：GetCapabilities → GetProfiles → 最小的 H.264 档案 → GetStreamUri
    │  把账号写进 RTSP 地址（页面看不到密码）
    ▼
ffmpeg（只在有人看的时候跑）
    rtsp_transport tcp → fps=20 → mjpeg q=5 → 一帧帧 JPEG
    │
    ▼
页面按 JPEG 的 FF D8 … FF D9 切帧，画到 <img>
```

关掉页面，或最后一个观看者断开，`Relay` 结束 ffmpeg，摄像头上的 RTSP 会话跟着断。语音对话不停。

## 各块做什么

| 位置 | 作用 |
| --- | --- |
| `thinksmart_client/camera.py` | ONVIF、选档案、起停 ffmpeg、把字节交给观看者。`show` 是语音开关：没配置摄像头就拒绝，否则发事件；打开时点一下屏幕把它点亮 |
| `thinksmart_client/web.py` | `GET /api/camera/live`。账号错误或连不上时返回 JSON 错误，不开始推流 |
| `thinksmart_client/mcp.py` | 工具 `self.camera.set`，参数 `open`。说法包括「打开摄像头」「看监控」「关闭摄像头」「关掉监控」「别看了」 |
| `thinksmart_client/device.py` | `Screen.watch`：看画面时让熄屏程序保持亮屏。和「对话中不熄屏」分开，关一个不会把另一个关掉 |
| `web/v2/` | 顶栏摄像头按钮（镜头朝侧面的摄像机图标）。快照里 `camera` 为 true 才显示。全屏层盖住主页，关闭按钮在层上面。闹钟层和关机层仍盖在它上面 |

账号在 `~/.config/thinksmart-client/config.json` 的 `camera` 里：`host`、`onvif_port`（这台是 80）、`user`、`password`。没有 `host` 时按钮不出现，语音工具回答「这台设备没有设置摄像头」。密码只留在这台设备上，不进页面，也不写进日志（日志里的 RTSP 地址会去掉账号）。

## 一次打开的过程

1. 按钮或 `self.camera.set open=true`。语音打开时先把屏幕点亮。
2. 页面显示「正在连接摄像头…」，请求 `GET /api/camera/live`。
3. 客户端用 WS-Security 密码摘要调 ONVIF，拿到子码流地址，再带上账号。
4. ffmpeg 用 TCP 拉 RTSP，每秒 20 帧，收成 JPEG。第一帧到达后，页面开始画，连接提示消失。
5. 关闭时页面中止这个请求。没有别的观看者时，ffmpeg 被停掉。

连不上、没有画面、或 ffmpeg 不在时，全屏层上显示原因，关闭按钮仍然能回到主页。
