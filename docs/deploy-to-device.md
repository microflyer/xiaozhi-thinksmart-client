# 把摄像头功能部署到设备

设备是 `192.168.31.211`，用 `ubuntu` 登录。正在跑的客户端在 `/opt/thinksmart/client/current`，这是指向 `0.1.6` 的链接。服务名是 `thinksmart-client`，以 `ubuntu` 运行，页面在 `127.0.0.1:8090`。

这次没有发新版本。设置页里的「软件更新」从本仓库的 Release 下载整包，换掉 `current`。那些 Release 里还没有摄像头功能，用它更新会把这次改动盖掉。所以部署是把改过的文件拷进正在跑的 `0.1.6`，再重启服务。

`ffmpeg` 不用装。设备上原来就有 `/usr/bin/ffmpeg`。

## 要拷哪些文件

在开发机的仓库里，摄像头功能涉及这些文件。测试和文档不用上设备。

- `thinksmart_client/camera.py`（新文件）
- `thinksmart_client/config.py`
- `thinksmart_client/device.py`
- `thinksmart_client/app.py`
- `thinksmart_client/web.py`
- `thinksmart_client/mcp.py`
- `web/v2/index.html`
- `web/v2/app.js`
- `web/v2/app.css`

虚拟环境不要拷。`0.1.6/.venv` 指到 `/opt/thinksmart/envs/c962717d64772981`，服务用的就是它。

## 拷上去并重启

在开发机的仓库目录执行。`ubuntu` 对本机 `sudo` 不需要再输密码。

```bash
tar -C . -czf /tmp/thinksmart-camera.tgz \
  thinksmart_client/camera.py \
  thinksmart_client/config.py \
  thinksmart_client/device.py \
  thinksmart_client/app.py \
  thinksmart_client/web.py \
  thinksmart_client/mcp.py \
  web/v2/index.html web/v2/app.js web/v2/app.css

scp /tmp/thinksmart-camera.tgz ubuntu@192.168.31.211:/tmp/thinksmart-camera.tgz

ssh ubuntu@192.168.31.211 'bash -lc "
  set -e
  rm -rf /tmp/thinksmart-camera && mkdir -p /tmp/thinksmart-camera
  tar -C /tmp/thinksmart-camera -xzf /tmp/thinksmart-camera.tgz
  sudo -n cp -a /tmp/thinksmart-camera/thinksmart_client/. /opt/thinksmart/client/current/thinksmart_client/
  sudo -n cp -a /tmp/thinksmart-camera/web/v2/. /opt/thinksmart/client/current/web/v2/
  sudo -n systemctl restart thinksmart-client
"'
```

重启会断开当前对话。服务起来要等 PipeWire 的套接字，通常几秒到十几秒。在设备上确认：

```bash
systemctl is-active thinksmart-client
curl -sf http://127.0.0.1:8090/api/health
```

第一条应是 `active`。页面发现这次启动和上次不是同一次，会自己重新加载，顶栏出现摄像头按钮。

看启动日志：

```bash
journalctl -u thinksmart-client -n 30 --no-pager -o cat
```

正常时能看到 `page on http://127.0.0.1:8090/`。如果进程反复重启，先看这里的报错，再用 [restore-backup.md](restore-backup.md) 回到改动前。

## 摄像头账号

程序文件里没有账号。账号在设备上的 `~/.config/thinksmart-client/config.json`，键是 `camera`：

- `host`：摄像头地址，这台是 `192.168.31.152`
- `onvif_port`：`80`
- `user`、`password`：摄像头的 ONVIF 账号

没有 `host` 时按钮不出现，语音工具会说没有设置摄像头。改这个文件之后要重启 `thinksmart-client` 才会读到。密码不要写进仓库。

## 和正式更新的差别

| | 这次的部署 | 设置页「软件更新」 |
| --- | --- | --- |
| 装到哪 | 直接改 `/opt/thinksmart/client/0.1.6` 里的文件 | 新版本目录，并把 `current` 指过去 |
| 虚拟环境 | 沿用原来的 | 随 Release 自带 |
| 失败时 | 用备份整份换回 `/opt/thinksmart` | 更新服务自己的自检失败会切回 `previous` |
| 以后再更新 | 设置页更新会盖掉这些文件 | 摄像头功能要先进 Release 才会留下来 |
