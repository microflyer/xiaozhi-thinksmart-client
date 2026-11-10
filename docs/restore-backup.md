# 恢复这次改动之前的客户端

备份是在加上摄像头功能之前做的，时间是 2026-11-10 19:43（+08），设备名 `thinksmarter`。当时正在跑的是 0.1.6（`current -> 0.1.6`，`previous -> 0.1.3`），对应源码提交 `e7ec0de`。

摄像头功能是直接改在正在跑的 `/opt/thinksmart/client/0.1.6` 上的，没有新开一个版本目录。要回到改动前，用这份备份盖回去。

## 备份在哪

两份内容相同，校验和都是：

`b1174a1ca896da9de0c297aacf2821a5deee162438191d020d816760fd26fe3f`

- 设备上的目录：`/home/ubuntu/thinksmart-client-backup-20261110`
- 设备上的压缩包：`/home/ubuntu/thinksmart-client-backup-20261110.tar.gz`（64 MB）
- 这台 Mac 上的同一份压缩包：`/Users/danny/Development/think-smart/backups/thinksmart-client-backup-20261110.tar.gz`

里面有当时的整个 `/opt/thinksmart`（客户端 0.1.6 和 0.1.3、虚拟环境、`system`），以及当时的用户配置和闹钟：

- `opt-thinksmart/` → 恢复到 `/opt/thinksmart`
- `home/config-thinksmart-client/` → `~/.config/thinksmart-client`
- `home/share-thinksmart-client/` → `~/.local/share/thinksmart-client`

`0.1.6/.venv` 是相对链接 `../../envs/c962717d64772981`。只有放回 `/opt/thinksmart/client/0.1.6` 才能指到虚拟环境。不要把这个目录挪到别处再启动。

## 在设备上恢复

用 `ubuntu` 登录 `192.168.31.211`，然后：

```bash
sudo systemctl stop thinksmart-client
sudo rm -rf /opt/thinksmart
sudo cp -a /home/ubuntu/thinksmart-client-backup-20261110/opt-thinksmart /opt/thinksmart
rm -rf /home/ubuntu/.config/thinksmart-client /home/ubuntu/.local/share/thinksmart-client
cp -a /home/ubuntu/thinksmart-client-backup-20261110/home/config-thinksmart-client /home/ubuntu/.config/thinksmart-client
cp -a /home/ubuntu/thinksmart-client-backup-20261110/home/share-thinksmart-client /home/ubuntu/.local/share/thinksmart-client
sudo systemctl start thinksmart-client
```

启动后 `systemctl is-active thinksmart-client` 应为 `active`，`curl -sf http://127.0.0.1:8090/api/health` 有响应。首页不再有摄像头按钮。

上面的配置和闹钟会回到备份那一刻。备份之后在页面上改过的亮度、闹钟、蓝牙开关也会被盖掉。如果只想撤掉摄像头程序、留下之后改过的设置，不要执行那两行 `rm` 和 `cp` 用户目录的命令；程序本身仍然要按前面的步骤换回 `/opt/thinksmart`。

## 设备上的备份没了

把 Mac 上的压缩包拷到设备再解压，目录结构相同，然后用上面的命令恢复：

```bash
scp /Users/danny/Development/think-smart/backups/thinksmart-client-backup-20261110.tar.gz ubuntu@192.168.31.211:/home/ubuntu/
ssh ubuntu@192.168.31.211 'tar -C /home/ubuntu -xzf /home/ubuntu/thinksmart-client-backup-20261110.tar.gz'
```

解压出来的路径就是 `/home/ubuntu/thinksmart-client-backup-20261110`。先对一下校验和：

```bash
sha256sum /home/ubuntu/thinksmart-client-backup-20261110.tar.gz
```

应等于本节开头的那个值。
