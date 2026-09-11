"""打包/直接运行入口: 与 `python -m transponder` 行为完全一致.

无参数=GUI; 带参数按 __main__ 分发规则 (--nogui=纯命令行, 查询类直接执行).
"""
from transponder.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
