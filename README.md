# MW数据转发器 (Data Transponder)

嵌入式调试用数据桥梁: 在 **串口 / TCP / UDP单播 / 组播 / 广播 / 文件** 之间互相转发数据。

技术栈: Python 3.10+ / PySide6 / pyserial / psutil, 支持 Windows / Linux。
UI 与命令行只是两个使用接口, 核心转发引擎完全同一套。深色/浅色主题可一键切换。

## 运行

```bash
pip install -r requirements.txt

python -m transponder            # 图形界面 (无参数)
python -m transponder -m "serial:port=COM3"        # 带参数仍打开UI, 并自动填充该配置
python -m transponder --nogui -m ... -w ...        # 纯命令行模式
python -m transponder --help                       # 命令行帮助
```

## GUI 使用流程

1. 左侧选择数据源 M 的类型并配置参数, 点 **打开数据源** (打开后参数变灰, 按钮下方出现对端列表/文件进度条)
2. 右侧同样配置数据源 W 并打开
3. 点 **▶ 开始转发**, M↔W 双向转发; 点 **■ 停止转发** 停止 (数据源保持打开, 可再次开始)

界面功能:
- 深色/浅色主题 + 圆角/直角风格一键切换; 提示消息为自动消失的浮动通知
- 数据源"打开"按钮绿色 / "关闭"按钮红色; 打开后配置锁定变灰 (文件限速除外)
- 每个数据源下方实时显示速率/累计流量, 串口额外显示带宽占用百分比 (按波特率推算); 停止转发后速率清零
- 数据预览分 M/W 左右两个区域, 各自独立: 显示开关 (滑动, 转发中即时生效) / HEX/TXT / 暂停/继续/清空; HEX 严格按原始字节显示 (0x0A 显示为 "0A" 不换行)
- TCP服务端 / 组播 / 广播的对端列表 (带接入序号, 打开时自动刷新), 可选择"主要对端" (TCP: 点对点; 不选: 发给全部收全部; 组播/广播: 只收主要对端)
- 文件发送: 进度条 + B/KB/MB 三滑块叠加限速 (可"不限速"; 转发过程中可动态调整), 智能单位显示
- 组播地址有效性检测 (224.0.0.0/4) + 本地网卡选择; 广播地址按网卡自动填充; TCP/UDP 端口占用检测; 串口占用标注
- 组播/广播自动过滤自己发出的回环数据, 本机其他程序可正常参与同机测试
- 落地记录分侧配置 (记录开关/格式/TXT时间戳间隔), 共用 basedir 在开始/停止按钮旁; 转发中配置锁定; 每次开始新建时间戳文件夹 `2026-09-10_11-20-56` (含 `M.bin/M.txt/W.bin/W.txt`), 停止后立即释放文件句柄
- 数字输入框"默认/自动"为淡色占位提示, 清空输入自动回到占位; 自动端口/监听队列在打开后回填实际值
- 最下方事件日志 (带统一宽度时间戳, 相同提示自动去重), 可清空

## 命令行 (无 UI) 用法

数据源规格为 `类型:参数=值,参数=值` 形式:

```bash
python -m transponder --list-serial          # 查看可用串口
python -m transponder --list-net             # 查看本机地址/广播地址

# 串口 <-> TCP客户端
python -m transponder --nogui -m serial:port=COM3,baud=115200 -w tcp-client:host=192.168.1.10,port=9000

# TCP客户端指定本地绑定 + TCP服务端指定监听队列
python -m transponder --nogui -m tcp-client:host=1.2.3.4,port=9000,local_host=192.168.1.5,local_port=0 \
                      -w tcp-server:port=9001,backlog=8

# TCP服务端指定主要对端 (不指定则发给全部客户端并接收全部)
python -m transponder --nogui -m tcp-server:port=9001,primary=192.168.1.7:40001 -w serial:port=COM3

# UDP单播: 对端可选; 未填对端时锁定第一帧数据的来源
python -m transponder --nogui -m udp:host=0.0.0.0,port=9000,peer=192.168.1.9:9001 -w file-recv:path=out.bin

# 文件限速发送 (b+1024*kb+1024*mb 字节每秒, 0/0/0=不限速) + 分侧落地记录
python -m transponder --nogui -m file-send:path=data.bin,b=500,kb=20,mb=0 \
                      -w tcp-server:port=9000 --log-dir logs --log-m --log-fmt-m bin

# 分侧格式: M=bin, W=txt+200ms时间戳
python -m transponder --nogui -m udp:port=9000 -w file-recv:path=out.bin \
                      --log-dir logs --log-m --log-w --log-fmt-w txt --log-ts-w 200

# 组播 (本地网卡可选, 自动过滤自身回环) / 广播 (可指定广播地址与本地端口)
python -m transponder --nogui -m multicast:group=239.1.1.1,port=5000,local_host=192.168.10.1 -w serial:port=COM3
python -m transponder --nogui -m broadcast:addr=192.168.10.255,port=5000,local_port=6000 -w tcp-client:host=x,port=9000
```

完整参数见 `--help` 或 `transponder/core/factory.py` 文件头注释。

## 打包 exe (可选)

```bash
pip install pyinstaller
# 先创建入口 run.py:  内容为  from transponder.gui import run_gui; raise SystemExit(run_gui())
pyinstaller -F -w -n transponder run.py
```

## 目录结构

```
transponder/
├── __main__.py       # 入口: 无参数/带参数且无--nogui → GUI(可预填充); --nogui → CLI
├── cli.py            # 命令行无UI模式
├── gui/              # PySide6 图形界面
│   ├── __init__.py   # run_gui 入口 (主题/图标/预填充)
│   ├── theme.py      # 黑白双主题 QSS+调色板 + 滑动开关 + 浮动通知(Toast)
│   ├── forms.py      # 各数据源类型的参数表单 (含对端列表/进度条逻辑所在面板)
│   ├── source_panel.py  # 单侧数据源面板 (类型/表单/打开/对端列表/统计)
│   ├── main_window.py   # 主窗口 (布局/预览+分侧记录/事件日志/主题切换)
│   └── assets/       # 图标资源 (下拉/SpinBox 箭头, 应用图标; PNG 由 SVG 预渲染)
└── core/             # 转发引擎 (纯Python, 无Qt依赖)
    ├── datasource.py # 数据源抽象基类 (含对端列表/进度回调协议)
    ├── serial_source.py  file_source.py  net_source.py
    ├── factory.py    # 规格字符串 -> 数据源实例
    └── bridge.py     # 转发桥 + 流量统计 + 落地记录 (bin/txt, 时间戳文件夹)
tests/                # 回环端到端测试
```
