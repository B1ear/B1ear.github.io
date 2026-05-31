---
title: 'Vue 3 + Flask 项目桌面化打包实战：从 Electron 到 PyWebview 的踩坑之路'
date: 2026-05-26 12:00:00
tags:
  - Electron
  - PyWebview
  - Vue 3
  - Flask
  - PyInstaller
  - 桌面应用
categories:
  - Development
---

## 背景

项目是一个 Vue 3 + Flask 的全栈应用（美伊双边数据动态安全采集系统），前端使用 Vite 构建，后端是 Flask + SQLAlchemy + SQLite。目标是将其打包为 Windows 桌面应用，双击即用，无需用户安装 Python 或 Node.js 环境。

---

## 方案一：Electron（失败）

### 初始架构

```
Electron 主进程
├── 启动 Flask 后端子进程
├── 创建 BrowserWindow 加载前端
└── 窗口关闭时杀死 Flask 进程
```

前端通过 Vite proxy 代理 `/api` 请求到 Flask 的 8080 端口。Electron 打包后，前端静态文件由 Electron 直接加载，API 请求改为直连 `http://localhost:8080/api`。

### 问题 1：`showSaveFilePicker` 报错

```
Failed to execute 'showSaveFilePicker' on 'Window': Must be handling a user gesture
```

**原因**：File System Access API 要求在用户点击事件的同步上下文中调用。代码中先做了 `await api.get()` 异步请求，用户手势上下文已丢失。

**解决**：把 `showSaveFilePicker` 移到 `await api.get()` 之前，先获取文件句柄，再异步请求数据、写入文件。

### 问题 2：Electron `require('electron')` 返回 undefined

```
TypeError: Cannot read properties of undefined (reading 'whenReady')
```

**原因**：在 Git Bash 中直接运行 `electron.exe .` 时，Node.js 模块解析器无法正确加载 Electron 内建模块。Electron 应用必须通过 `npx electron .` 或打包后的 exe 启动。

**解决**：开发时使用 `npx electron .`，不要直接调用 `electron.exe`。

### 问题 3：打包后窗口空白

**原因**：Vite 构建的 HTML 使用绝对路径 `/assets/index-xxx.js`，在 `file://` 协议下会解析到系统根目录。

**解决**：在 `vite.config.js` 中添加 `base: './'`，让构建产物使用相对路径。

### 问题 4：PyInstaller + conda 的 DLL 灾难

```
ImportError: DLL load failed while importing pyexpat
```

**原因**：conda 环境的 Python 有大量系统级 DLL 依赖，PyInstaller 无法正确打包这些 DLL。这是 conda + PyInstaller 的已知兼容性问题。

**尝试过的解决方案**：

- `--paths` 添加 conda DLL 目录 → 无效
- `--collect-all` 收集所有依赖 → 无效
- 使用 `--onefile` 模式 → 同样的 DLL 错误

**最终结论**：conda 环境不适合用 PyInstaller 打包。必须使用系统 Python 创建 venv。

### 问题 5：Electron 找不到 Python

打包后的 Electron 应用需要启动 Flask 后端，但：

- 系统 Python 没有 Flask 等依赖
- conda Python 路径硬编码，换机器就失效
- 用 batch 脚本启动 Python 进程也不可靠

### 问题 6：`log()` 函数无限递归

用 `sed` 批量替换 `console.log` 为 `log` 时，把 `log` 函数体内的 `console.log` 也替换了，导致：

```javascript
function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`
  log(msg)  // ← 无限递归，栈溢出
}
```

应用启动瞬间崩溃，无任何错误输出。

### 放弃 Electron 的原因

| 问题 | 严重程度 |
|------|---------|
| Node.js + Python 双进程管理复杂 | 高 |
| PyInstaller + conda DLL 不兼容 | 致命 |
| 前端 file:// 协议路径问题 | 中 |
| 打包后 Python 路径硬编码 | 高 |
| 调试困难（GUI 应用无控制台输出） | 高 |

**核心矛盾**：Electron 是 Node.js 生态，而后端是 Python。两者之间的进程管理在打包后极其脆弱。

---

## 方案二：PyWebview（成功）

### 架构

```
单个 Python 进程
├── Flask 在后台线程运行（端口 8080）
├── PyWebview 打开原生窗口加载 http://127.0.0.1:8080
└── 窗口关闭 → 进程退出
```

### 优势

| 对比项 | Electron | PyWebview |
|--------|----------|-----------|
| 依赖 | Node.js + Python | 仅 Python |
| 进程数 | 2（Electron + Flask） | 1 |
| 打包工具 | electron-builder + PyInstaller | 仅 PyInstaller |
| 前端加载 | file:// 协议（需特殊处理） | http://localhost（天然支持） |
| 窗口 | Chromium（~180MB） | 系统 WebView（~0MB） |
| 打包体积 | ~200MB | ~134MB |

### 实现

#### desktop.py — 桌面入口

```python
import sys
import os
import threading

# PyInstaller onefile 模式：打包的文件在 sys._MEIPASS 临时目录
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = sys._MEIPASS
    EXE_DIR = os.path.dirname(sys.executable)
    # 抑制控制台输出
    import io
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = BUNDLE_DIR

sys.path.insert(0, os.path.join(BUNDLE_DIR, 'backend'))

def main():
    import logging
    import webview
    from app import app
    from models import db

    if getattr(sys, 'frozen', False):
        app.logger.setLevel(logging.ERROR)
        logging.getLogger('werkzeug').setLevel(logging.ERROR)

    with app.app_context():
        db.create_all()

    # Flask 服务前端静态文件
    frontend_dist = os.path.join(BUNDLE_DIR, 'frontend', 'dist')
    if os.path.isdir(frontend_dist):
        from flask import send_from_directory

        @app.route('/')
        def serve_index():
            return send_from_directory(frontend_dist, 'index.html')

        @app.route('/<path:path>')
        def serve_static(path):
            file_path = os.path.join(frontend_dist, path)
            if os.path.isfile(file_path):
                return send_from_directory(frontend_dist, path)
            return send_from_directory(frontend_dist, 'index.html')

    def start_server():
        app.run(host='127.0.0.1', port=8080, debug=False, use_reloader=False)

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    import time
    time.sleep(1.5)

    window = webview.create_window(
        title='数据动态安全采集系统',
        url='http://127.0.0.1:8080',
        width=1600, height=1000,
        min_size=(1200, 700),
    )
    webview.start(debug=False)

if __name__ == '__main__':
    main()
```

#### 前端 API 适配

```javascript
// Electron 环境用绝对路径，开发/PyWebview 用相对路径
const isElectron = window.location.protocol === 'file:'
const apiBaseURL = isElectron ? 'http://localhost:8080/api' : '/api'
```

#### app.py 数据库路径适配

```python
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)  # exe 所在目录
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 开发模式
```

### 打包脚本 build.bat

```batch
@echo off
chcp 65001 >nul

set PYTHON_EXE=C:\Python313\python.exe

:: 1. 构建前端
cd frontend && call npm run build && cd ..

:: 2. 创建 venv（关键：不用 conda）
%PYTHON_EXE% -m venv build_venv
call build_venv\Scripts\activate.bat

:: 3. 安装依赖
python -m pip install flask flask-cors flask-sqlalchemy requests waitress pywebview pyinstaller --quiet

:: 4. 打包（--windowed 无控制台，--hidden-import 确保依赖完整）
python -m PyInstaller --noconfirm --onefile --windowed --name SecureCollect ^
    --add-data "frontend/dist;frontend/dist" ^
    --add-data "backend;backend" ^
    --hidden-import flask --hidden-import flask_sqlalchemy ^
    --hidden-import flask_cors --hidden-import waitress ^
    --hidden-import webview --hidden-import requests ^
    --collect-all webview desktop.py

deactivate

:: 5. 复制数据库到 exe 同级目录
copy /Y backend\data.db dist\data.db

:: 6. 清理
rmdir /s /q build_venv build 2>nul
del SecureCollect.spec 2>nul
```

### PyInstaller 关键参数

| 参数 | 作用 |
|------|------|
| `--onefile` | 打包为单个 exe |
| `--windowed` | 无控制台窗口（GUI 应用） |
| `--add-data "src;dest"` | 打包非 Python 文件（前端静态文件、后端代码） |
| `--hidden-import mod` | 显式包含 PyInstaller 无法自动检测的模块 |
| `--collect-all pkg` | 收包整个包（pywebview 需要） |

### 最终输出

```
dist/
├── SecureCollect.exe  (134MB)  ← 主程序
└── data.db            (463MB)  ← 数据库
```

发给别人时，两个文件放同一目录，双击 exe 即可运行。

---

## 总结

| 阶段 | 耗时 | 结果 |
|------|------|------|
| Electron + PyInstaller (conda) | ~3h | 失败，DLL 不兼容 |
| Electron + 系统 Python venv | ~1h | 失败，进程管理复杂 |
| PyWebview + venv | ~30min | 成功 |

**经验教训**：

1. **conda + PyInstaller = 灾难**。打包 Python 应用务必用系统 Python 创建 venv。
2. **Electron 适合纯 Node.js 项目**。一旦涉及其他语言的后端，进程管理会变得极其复杂。
3. **PyWebview 是 Python 全栈项目的最佳桌面化方案**。单进程、体积小、无需额外运行时。
4. **`file://` 协议是 Electron 的大坑**。任何涉及相对路径的前端资源都需要特殊处理。
5. **GUI 应用调试要写日志文件**。`console.log` 在打包后不可见，`sys.stdout` 在 windowed 模式下被丢弃。
