# MW数据转发器 (Data Transponder)

嵌入式调试用数据桥梁: 在 **串口 / TCP / UDP单播 / 组播 / 广播 / 文件** 之间互相转发数据。

技术栈: Python 3.10+ / PySide6 / pyserial / psutil, 支持 Windows / Linux。
**GUI 给人类使用, 命令行给脚本/AI agent 使用**, 两者共享同一套 core 转发引擎, 功能一致。
版本号与 git 提交序列对应, `--version` / GUI 标题同源显示。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/需求设计.md](docs/需求设计.md) | 总体需求 (数据源规则/转发控制/UI 外观) |
| [docs/CLI设计说明.md](docs/CLI设计说明.md) | 命令行设计: 定位/入口分发/退出码/规格语法/行为语义 |
| [docs/CLI使用说明.md](docs/CLI使用说明.md) | 命令行使用: 场景示例/AI agent 调用建议/与 GUI 差异 |
| docs/修改意见1~5.md | 历轮修改意见存档 |

## 运行

```bash
pip install -r requirements.txt

python -m transponder            # 图形界面 (无参数)
python -m transponder -m "serial:port=COM3"        # 带参数仍打开UI, 并自动填充该配置
python -m transponder --nogui -m ... -w ...        # 纯命令行模式 (单次运行, 适合 agent)
python -m transponder --help                       # 命令行帮助 (含规格语法与示例)
python -m transponder --version                    # 版本号
```

命令行是**单次运行式**: 参数即配置, 立即开始转发, Ctrl+C 或 `--duration 秒` 停止退出;
要改配置就退出后重新执行。stdout/stderr 可捕获, 退出码 0/1/2/3 可判断 (详见 CLI 设计说明)。

## GUI 使用流程

1. 左侧选择数据源 M 的类型并配置参数, 点 **打开** (绿色; 打开后变红色"关闭", 参数变灰)
2. 右侧同样配置数据源 W 并打开
3. 点 **▶ 开始转发**, M↔W 双向转发; 点 **■ 停止转发** 停止 (数据源保持打开, 可再次开始)

界面功能:
- 深色/浅色主题 + 圆角/直角风格一键切换; 启动时白天(08:00~20:00)默认浅色、夜间默认深色; Windows 10 默认直角、Windows 11/其他系统默认圆角
- 提示消息为自动消失的浮动通知; 打开数据源后配置锁定变灰 (文件限速联动控件除外)
- 每个数据源对应的数据预览区底部显示速率/累计流量 (串口额外显示带宽占用百分比), 停止转发后速率清零
- 数据预览分 M/W 左右两个区域, 各自独立: 显示开关 (滑动, 转发中即时生效) / HEX/TXT / 暂停/继续/清空; HEX 严格按原始字节显示 (0x0A 显示为 "0A" 不换行)
- TCP服务端 / 组播 / 广播的对端列表 (带接入序号, 打开时自动刷新), 可选择"主要对端"
- 文件发送: 进度条 + B/KB/MB 三滑块叠加限速 (转发中可动态调整), 智能单位显示
- 组播地址有效性检测 (224.0.0.0/4) + 本地网卡选择; 广播地址按网卡自动填充; TCP/UDP 端口占用检测; 串口占用标注
- 组播/广播自动过滤自己发出的回环数据, 本机其他程序可正常参与同机测试
- 落地记录分侧配置 (记录开关/格式/TXT时间戳间隔), 共用 basedir 在开始/停止按钮旁; 每次开始新建时间戳文件夹 `2026-09-10_11-20-56` (含 `M.bin/M.txt/W.bin/W.txt`), 停止后立即释放文件句柄
- 数字输入框"默认/自动"为真正空值的淡色占位提示, 清空输入自动回到占位; 自动端口/监听队列在打开后回填实际值, 关闭后恢复占位
- 事件日志每行带统一宽度时间戳, 支持暂停/继续 (暂停期间缓存不丢失)、清空、导出

## 命令行速览

```bash
python -m transponder --list-serial          # 查看可用串口 (占用状态)
python -m transponder --list-net             # 查看本机地址/广播地址

# 串口 <-> TCP客户端
python -m transponder --nogui -m serial:port=COM3,baud=115200 -w tcp-client:host=192.168.1.10,port=9000
# TCP服务端主要对端 / UDP单播对端锁定
python -m transponder --nogui -m "tcp-server:port=9001,primary=192.168.1.7:40001" -w serial:port=COM3
# 文件限速发送 + 分侧落地记录 (M=bin, W=txt+200ms时间戳)
python -m transponder --nogui -m file-send:path=data.bin,b=500,kb=20 -w tcp-server:port=9000 \
                      --log-dir logs --log-m --log-fmt-m bin --log-w --log-fmt-w txt --log-ts-w 200
# 组播 / 广播 (自动过滤自身回环)
python -m transponder --nogui -m multicast:group=239.1.1.1,port=5000 -w serial:port=COM3
python -m transponder --nogui -m broadcast:addr=192.168.10.255,port=5000 -w tcp-client:host=x,port=9000
# 30秒后自动退出
python -m transponder --nogui --duration 30 -m ... -w ...
```

完整规格语法 (8 种数据源的全部参数) 见 `--help` 尾部或 [docs/CLI使用说明.md](docs/CLI使用说明.md)。

## 打包 exe

```bash
pip install pyinstaller pillow
# 生成 ico (一次性)
python -c "from PIL import Image; img=Image.open('transponder/gui/assets/app-icon.png'); img.save('transponder/gui/assets/app-icon.ico', sizes=[(256,256),(64,64),(32,32),(16,16)])"
pyinstaller -F -w -n MWTransponder \
  -i transponder/gui/assets/app-icon.ico \
  --add-data "transponder/gui/assets;transponder/gui/assets" \
  run.py
```

产物 `dist/MWTransponder.exe`:
- **双击** → 直接打开 GUI (无控制台窗口弹出)
- **终端里带参数** → 自动附加父控制台, 正常使用命令行模式 (输出/退出码可用)
- **被脚本/agent 以管道调用** → stdout/stderr 天然可用
- 打包前更新 `transponder/_version.py` (与 git tag 保持一致)

## 目录结构

```
docs/                 # 需求/修改意见存档 + CLI 设计与使用说明
run.py                # 打包/直接运行入口 (与 python -m transponder 一致)
transponder/
├── __main__.py       # 入口分发: 无参→GUI; 带参无--nogui→GUI预填充; --nogui→CLI; 查询类直接执行
├── _version.py       # 版本号 (git 提交序列)
├── cli.py            # 命令行模式 (单次运行式, 适合 agent)
├── gui/              # PySide6 图形界面
│   ├── __init__.py   # run_gui 入口 (主题/图标/预填充/Qt日志过滤)
│   ├── theme.py      # 黑白双主题+圆角直角 QSS/调色板 + 滑动开关 + Toast + 占位数值框
│   ├── forms.py      # 各数据源类型的参数表单
│   ├── source_panel.py  # 单侧数据源面板 (类型/表单/打开/对端列表/进度)
│   ├── main_window.py   # 主窗口 (布局/预览+分侧记录/事件日志/主题切换/统计)
│   ├── util.py       # 格式化工具
│   └── assets/       # 图标资源 (下拉/SpinBox 箭头, 应用图标)
└── core/             # 转发引擎 (纯Python, 无Qt依赖)
    ├── datasource.py # 数据源抽象基类 (对端列表/进度回调协议)
    ├── serial_source.py  file_source.py  net_source.py
    ├── factory.py    # 规格字符串 -> 数据源实例
    └── bridge.py     # 转发桥 + 流量统计 + 落地记录
tests/                # 端到端测试: test_loopback / test_udp_serial / test_features / test_gui_v4 / test_cli
```
