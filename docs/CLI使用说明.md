# MW数据转发器 · 命令行使用说明

> 对应版本: v6.4。完整参数语法见 `--help`, 设计细节见 [CLI设计说明.md](CLI设计说明.md)。

## 1. 运行方式

```bash
# 源码运行
python -m transponder --help
python -m transponder --nogui -m <SPEC> -w <SPEC>

# exe (双击=GUI; 在终端里带参数=命令行)
MWTransponder.exe --help
MWTransponder.exe --nogui -m <SPEC> -w <SPEC>
```

单次运行式: 参数即配置, 立即开始转发; `Ctrl+C` 或 `--duration 秒数` 停止退出;
要改配置就退出后重新执行。适合脚本和 AI agent (stdout 可捕获、退出码可判断)。

## 2. 先探测环境, 再配置

```bash
# 看有哪些串口 (含占用状态) —— 串口名填进 serial:port=
MWTransponder.exe --list-serial
# COM3  [可用]  USB Serial Port (COM3)

# 看本机地址与各网卡广播地址 —— 填绑定地址/广播地址
MWTransponder.exe --list-net
# 本机地址:   0.0.0.0 / 127.0.0.1 / 192.168.1.220 ...
# 广播地址:   255.255.255.255 / 192.168.1.255 / 192.168.10.255 ...
```

## 3. 常用场景

### 串口 ↔ TCP (把设备数据送到网络, 或反向)
```bash
python -m transponder --nogui \
  -m serial:port=COM3,baud=115200,data=8,parity=N,stop=1 \
  -w tcp-client:host=192.168.1.10,port=9000
```

### 本机起 TCP 服务端等设备/工具连入
```bash
# 不指定 primary: 发给全部客户端并接收全部
python -m transponder --nogui -m tcp-server:port=9000 -w serial:port=COM3
# 指定 primary: 只与 192.168.1.7:40001 点对点
python -m transponder --nogui -m "tcp-server:port=9000,primary=192.168.1.7:40001" -w serial:port=COM3
```

### 文件限速发送 (模拟低速数据源)
```bash
# 限速 = 500B + 20KB = 20972 B/s; 读完自动结束该方向
python -m transponder --nogui -m "file-send:path=data.bin,b=500,kb=20" -w tcp-server:port=9000
```

### 把网络数据落成文件
```bash
python -m transponder --nogui -m udp:port=9000 -w "file-recv:path=capture.bin,append=0"
```

### UDP 单播
```bash
# 对端未知: 收到第一帧后自动锁定来源
python -m transponder --nogui -m udp:port=0 -w serial:port=COM3
# 对端已知 (仅与该对端收发)
python -m transponder --nogui -m "udp:host=0.0.0.0,port=9000,peer=192.168.1.9:9001" -w serial:port=COM3
```

### 组播 / 广播 (自动过滤自己发出的回环)
```bash
python -m transponder --nogui -m multicast:group=239.1.1.1,port=5000,ttl=1 -w serial:port=COM3
python -m transponder --nogui -m "broadcast:addr=192.168.10.255,port=5000" -w tcp-client:host=x,port=9000
```

### 数据落地记录 (抓包)
```bash
# M 侧存 BIN, W 侧存 TXT + 每200ms时间戳; 每次运行新建时间戳文件夹
python -m transponder --nogui -m udp:port=9000 -w file-recv:path=out.bin \
  --log-dir logs --log-m --log-fmt-m bin --log-w --log-fmt-w txt --log-ts-w 200
```

### 定时退出
```bash
python -m transponder --nogui --duration 30 -m ... -w ...   # 30秒后自动停止退出
```

## 4. 输出与退出码

```
[事件] 转发已开始                <- stdout, 运行期事件
[事件] 客户端 127.0.0.1:52344 已接入
进度: 51200/102400 (50%)         <- file-send 进度 (约每256KB刷新)
结束: M→W 102400 字节, W→M 0 字节 <- 最后一行摘要
```

| 退出码 | 含义 |
|---|---|
| 0 | 正常结束 |
| 1 | 运行错误 (连接失败/文件不存在等, 见 stderr) |
| 2 | 参数错误 (见 stderr, 格式问题先 `--help`) |
| 3 | 无图形环境 (仅 GUI 路径) |

## 5. AI agent 调用建议

1. **先探测**: `--list-serial` / `--list-net` 获取可用串口名与本机地址, 再拼 SPEC;
2. **限时**: 不确定时长时用 `--duration` 兜底, 避免进程常驻;
3. **判断结果**: 解析最后一行 `结束: M→W X 字节, W→M Y 字节` (X/Y=0 通常说明链路不通或无数据);
4. **捕获事件**: `[事件]` 前缀的行含客户端接入/断开、文件读完、对端锁定等状态, 可用于流程判断;
5. **诊断失败**: stderr 的 `错误: ...`/`参数错误: ...` + 退出码 1/2;
6. SPEC 含逗号/冒号时记得加引号 (示例中已标注)。

## 6. 与 GUI 的差异 (同一 core, 仅接口不同)

| 能力 | GUI | CLI |
|---|---|---|
| 数据预览 (HEX/TXT/暂停) | ✅ | ❌ (用落地记录代替) |
| 文件限速动态调整 | ✅ 滑块实时 | ❌ 仅启动时固定 (b/kb/mb) |
| 主要对端切换 | ✅ 界面点选 | ✅ 仅启动时 primary= 指定 |
| 停止方式 | 按钮 | Ctrl+C / --duration |
| 参数预填充 | ✅ (带参启动不开 --nogui) | — |
