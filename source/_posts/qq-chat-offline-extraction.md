---
title: QQ NT 聊天记录离线提取：从备份格式排查到单会话导出
date: 2026-10-15 00:00:00
categories:
  - reverse
tags:
  - QQ NT
  - SQLite
  - SQLCipher
  - Protobuf
  - 数据提取
  - 实战复盘
---

> 实战复盘 | 从官方备份格式排查到原始数据库副本的单会话导出

想把 QQ 中某个联系人的历史消息保存成可以检索、分析的文件，第一反应通常是使用客户端自带的导出功能。我也是从一份官方导出的 `.bak` 开始排查，先检查容器结构，再尝试开源解密工具，最后在本机原始聊天数据库的副本上完成了单会话提取。

最终得到三种文件：保留原始字段的 SQLite 数据库、适合程序处理的 JSONL，以及方便直接阅读的文本。本文记录跑通的流程，也保留没有解决的问题：**这次没有解开官方 `.bak` 内部数据库；成功提取的数据来自同账号的原始 `nt_msg.db` 副本。**

文中的账号、联系人、UID、密钥、用户目录、聊天时间、精确记录数量及私有文件哈希均已省略。路径和文件名是复现用的通用示例，没有使用真实消息作为样例。

## 0x01 先划清几个不同的步骤

这次工作实际包含三层处理：

```text
识别文件格式 → 用正确参数解密数据库页 → 解析消息字段中的 Protobuf
```

解开 ZIP 容器，并不意味着其中的数据库已经解密。能读取 SQLite 表结构，也不意味着图片、语音、引用回复等内容已经全部转换成可读文本。

跑通的主流程如下：

```text
已有数据库密钥
       ↓
确认同账号原始 nt_msg.db 的位置
       ↓
准备静止、完整的离线副本
       ↓
识别 QQ_NT DB 扩展头，复制并剥离前 1024 字节
       ↓
SQLCipher 只读打开，实际查询 sqlite_master 验证
       ↓
QQ 号与 UID 映射 → 筛选目标私聊记录
       ↓
先保存原始字段到独立 SQLite
       ↓
原仓库解析器 + 有明确字段依据的 wire fallback
       ↓
JSONL / 文本 → 数量、归属、顺序及完整性校验
```

数据库密钥提取需要单独看待。[qq-win-db-key 的 Windows 脚本](https://github.com/QQBackup/qq-win-db-key/blob/master/scripts/windows/ntqq/windows_ntqq_get_key.ps1)会启动 QQ 并附加调试器；之后的副本处理则不需要操作 QQ 进程。因此，只读副本可以减少后续处理对客户端的干预，但不能据此承诺“整套流程零风控风险”。

## 0x02 使用到的工具与环境

以下列出本次涉及的核心工具、依赖与脚本运行环境，链接均指向对应 GitHub 仓库。

| 工具或组件 | GitHub 仓库 | 本次用途 |
| --- | --- | --- |
| qq-win-db-key | [QQBackup/qq-win-db-key](https://github.com/QQBackup/qq-win-db-key) | 提取同账号原始数据库的密钥，并核对提取脚本行为 |
| nt_msg_db_util | [QQBackup/nt_msg_db_util](https://github.com/QQBackup/nt_msg_db_util) | 主要参考实现；采用解密参数、消息解析器和字段定义 |
| ntdb_unwrap | [artiga033/ntdb_unwrap](https://github.com/artiga033/ntdb_unwrap) | 实际运行的备用解密工具，用于交叉验证 |
| sqlcipher3 | [coleifer/sqlcipher3](https://github.com/coleifer/sqlcipher3) | SQLCipher 的 Python 绑定，用于读取加密数据库副本 |
| SQLCipher | [sqlcipher/sqlcipher](https://github.com/sqlcipher/sqlcipher) | 底层数据库加密引擎，通过 Python 绑定及备用工具使用 |
| Protocol Buffers | [protocolbuffers/protobuf](https://github.com/protocolbuffers/protobuf) | Python `protobuf` runtime，解析消息正文 |
| python-dotenv | [theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) | 原始 `1.decrypt.py` 的导入依赖；本次禁用 `.env` 自动加载，未用它保存密钥 |
| Python / CPython | [python/cpython](https://github.com/python/cpython) | 执行处理脚本；标准库 `zipfile` 读取容器，`sqlite3` 写入明文库，`hashlib` 校验文件 |
| SQLite | [sqlite/sqlite](https://github.com/sqlite/sqlite) | 明文导出数据库引擎；该链接是 SQLite 的官方 GitHub 镜像 |
| PowerShell | [PowerShell/PowerShell](https://github.com/PowerShell/PowerShell) | Windows 下执行脚本与文件操作；此仓库对应开源 PowerShell，Windows PowerShell 5.1 是不同版本线 |

另外参考了 [QQBackup/QQDecrypt](https://github.com/QQBackup/QQDecrypt) 的数据库提取与解密教程。它属于参考文档，没有作为另一个独立解密程序运行。`zipfile`、`sqlite3`、`hashlib`、`getpass` 等属于 Python 标准库，无需各自寻找第三方仓库。

实测最小处理链使用 Python 3.13、`sqlcipher3==0.6.4` 和 `protobuf==7.34.1`；SQLCipher 引擎报告的版本为 4.19.0，备用程序报告的版本为 0.3.3。这些版本描述的是本次实验环境，不代表其他 QQ 版本、数据库格式或未来仓库版本均兼容。

当时上游项目的 `pyproject.toml` 声明 Python ≥ 3.14；这里直接调用了其中可在 Python 3.13 运行的解密和解析模块。使用完整上游项目时，应遵循其自己的运行环境要求。

复现时可以建立独立目录：

```text
qq-lab/
├── QQ聊天记录离线提取实践.md    # 可公开的文章
├── qq_chat_export_example.py  # 可公开的通用示例代码
├── .venv/
├── sources/
│   └── nt_msg_db_util/
└── private_work/              # 数据、密钥相关操作和导出结果只留在本地
    ├── export.bak
    ├── snapshot/
    │   └── nt_msg.db
    └── selected_chat/
```

下面是准备依赖的 PowerShell 命令。示例代码使用本地检出的上游 `msgdb` 模块，不要求把整个上游项目安装进 Python 环境。

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install sqlcipher3==0.6.4 protobuf==7.34.1
git clone https://github.com/QQBackup/nt_msg_db_util.git .\sources\nt_msg_db_util
git -C .\sources\nt_msg_db_util rev-parse HEAD
```

最后一行用于记录自己拿到的源码版本。若后续更新源码，应重新核对参数、表结构和生成的 Protobuf 代码，不能只沿用旧依赖版本。

## 0x03 密钥提取成功，仍然需要验证

本次已有一份通过上游脚本提取的密钥。核对脚本后发现，它会读取目标函数参数中的字符串，在找到符合格式的 16 字节可打印 ASCII 字符串后结束提取；这一步本身没有通过打开目标数据库来验证密钥。

因此，日志中的“找到密钥”只能作为后续验证的输入。

如果需要从头准备，可以先从上游下载并检查脚本，再在自己的 QQ 环境中执行。不要把取得的真实密钥或完整调试日志粘贴到文章里：

```powershell
New-Item -ItemType Directory -Force .\private_work | Out-Null
Invoke-WebRequest `
  -Uri 'https://raw.githubusercontent.com/QQBackup/qq-win-db-key/master/scripts/windows/ntqq/windows_ntqq_get_key.ps1' `
  -OutFile .\private_work\windows_ntqq_get_key.ps1

# 检查脚本后，在需要提取密钥的环境中运行：
& .\private_work\windows_ntqq_get_key.ps1
```

密钥里可能包含分号、百分号、尖括号等字符。Markdown 转义符与密钥本身要分清，也不要让 shell 再解释这些字符。本文配套示例通过 Python 的 `getpass.getpass()` 隐藏输入，不把密钥写入源码、命令行参数或输出报告。

## 0x04 `.bak` 的第一层只是容器

这次样本可以由 Python `zipfile` 打开，里面有 `db/` 与 `files/` 两类条目。先读取数据库条目的前 1024 字节，就能获得很有用的判断依据，无须立即解出所有附件。

```python
from pathlib import Path
import zipfile

backup = Path('private_work/export.bak')
with zipfile.ZipFile(backup, 'r') as archive:
    for index, entry in enumerate(
        item for item in archive.infolist()
        if item.filename.startswith('db/') and not item.is_dir()
    ):
        with archive.open(entry) as stream:
            header = stream.read(1024)
        # 只显示格式标记，不展示条目名称、密钥元数据或完整十六进制内容。
        print(index, header[:16], header[32:40])
```

这份备份中的数据库有两个特征：文件前缀为 `SQLite header 3`，偏移 32 处为 `MSG0`。后面找到的本机原始库在相同位置则是 `QQ_NT DB`。

| 文件 | 这次观察到的结构 | 处理结果 |
| --- | --- | --- |
| 官方 `.bak` | ZIP64 容器，内部数据库带 `MSG0` 标记 | 可以读取容器；内部数据库解密未成功 |
| 本机 `nt_msg.db` | 扩展头中带 `QQ_NT DB` 标记 | 提供的密钥和原仓库参数可以读取 |
| 剥离扩展头的副本 | 开头仍是加密数据 | 需要 SQLCipher，不能直接当普通 SQLite 打开 |

这些是本次样本的实测结果，不应推广为所有 QQ `.bak` 的固定规范。共同的 `SQLite header 3` 前缀也不足以证明它们使用同一种密钥或同一套参数。

读取前缀只能做格式探测。若要验证整个 ZIP 条目的 CRC，必须将该条目读到 EOF；这次对实际完整解包的数据库副本做了这一检查。

## 0x05 先验证工具，再判断密钥是否匹配

最初按 `nt_msg_db_util` 的流程剥离扩展头并尝试读取备份库，出现了以下错误：

```text
hmac check failed for pgno=1
file is not a database
```

这些错误并不能直接证明账号密钥提取失败。密钥、起始偏移、页大小、KDF 参数、HMAC 算法或输入文件格式不匹配，都可能让第一页读取失败。

这次做了三类对照：

1. 使用相同 SQLCipher 参数生成只含合成数据的小数据库，再用原方法读回，确认依赖与基本流程能工作。
2. 尝试原仓库配置、SQLCipher 兼容配置及备用工具支持的 HMAC 变体，检查备份库是否能读取表结构。
3. 找到同账号本机的 `settings.db` 与 `nt_msg.db`，在副本上验证同一密钥。

第三步提供了关键证据：设置库可以读取，完整聊天库副本也可以读取表结构和消息。于是可以确认密钥对本机原始库有效，同时保留更窄的失败结论：**这把密钥与已测试的参数，未能打开此次 `.bak` 中的数据库。**

另外，聊天库的截取样本曾报 `database disk image is malformed`，完整副本却能读取表结构。小样本可以用于初筛，但数据库可能引用样本之外的页，不能用这种错误单独认定原库损坏。

## 0x06 备用工具怎样参与排查

在前一种方法无法打开备份库后，又检查了 `ntdb_unwrap` 的命令行帮助和源码，并采用显式文件、显式密钥的导出模式交叉验证。

```powershell
.\ntdb_unwrap.exe --version
.\ntdb_unwrap.exe export --help
```

参数形式如下，尖括号中的内容只是说明占位符：

```text
ntdb_unwrap.exe export "<DATABASE_COPY>" --pkey "<DB_KEY>" --output "<NEW_OUTPUT_DB>"
```

该版本在不提供密钥时会尝试自动提取；Windows 下这会进入启动 QQ 和调试进程的路径。显式指定 `--pkey` 后才是这里需要的手动密钥模式。默认还会复制输入文件到临时文件，本次保留了复制行为，没有启用 `--nocopy`。

实际调用通过 Python 子进程参数列表传入密钥，保存日志前替换掉密钥内容。命令行参数仍可能被本机进程查看工具看到，所以这与主流程中的隐藏输入方式并不完全等价。

备用工具对备份库也报第一页 HMAC 校验失败；对同账号设置库副本则可以成功导出。两种工具的对照进一步说明，应优先检查输入文件的格式与适用范围。

## 0x07 找到原始库，并准备稳定副本

Windows 上常见的原始库位置是：

```text
<QQ_DATA_ROOT>\<ACCOUNT>\nt_qq\nt_db\nt_msg.db
```

实际数据根目录可能被用户改到其他磁盘，不能只查默认“文档”目录。应通过 QQ 的数据目录设置，或在已知 QQ 数据目录中查找。

复制前正常退出客户端，使数据库处于静止状态。如果存在尚未合并的非空 `nt_msg.db-wal`，单独复制主库可能缺少已提交记录；需要先取得一致的快照，再使用后续流程。仅比较文件大小和修改时间，不能证明一个正在写入的数据库副本具有事务一致性。

```powershell
$sourceDb = Read-Host '输入原始 nt_msg.db 的完整路径'
$sourceWal = $sourceDb + '-wal'
if ((Test-Path -LiteralPath $sourceWal) -and
    (Get-Item -LiteralPath $sourceWal).Length -gt 0) {
    throw '原库旁仍有非空 WAL，请先准备一致的数据库快照'
}
New-Item -ItemType Directory -Force .\private_work\snapshot | Out-Null
if (Test-Path -LiteralPath .\private_work\snapshot\nt_msg.db) {
    throw '快照已存在，请使用新的私有工作目录'
}
Copy-Item -LiteralPath $sourceDb -Destination .\private_work\snapshot\nt_msg.db

$sourceHash = (Get-FileHash -LiteralPath $sourceDb -Algorithm SHA256).Hash
$copyHash = (Get-FileHash -LiteralPath .\private_work\snapshot\nt_msg.db -Algorithm SHA256).Hash
if ($sourceHash -ne $copyHash) { throw '源文件与副本不一致，请重新准备静止副本' }
```

后续全部操作都指向 `private_work/snapshot/nt_msg.db`。配套示例还会再生成剥离扩展头的工作文件，避免修改输入快照。示例只能检测输入快照旁的 WAL，无法发现复制时已经遗漏的原库 WAL，因此前面的快照准备不能省略。

## 0x08 剥离扩展头，再实际触发一次解密

对已确认的原始 NTQQ 库，本次使用 1024 字节扩展头长度、4096 字节页大小，以及下面这组参数。

```python
from pathlib import Path
import sqlcipher3.dbapi2 as sc

def open_payload(payload: Path, key: str):
    uri = payload.resolve().as_uri() + '?mode=ro&immutable=1'
    conn = sc.connect(uri, uri=True)
    conn.execute('PRAGMA cipher_page_size=4096')
    conn.execute("PRAGMA key='" + key.replace("'", "''") + "'")
    conn.execute('PRAGMA kdf_iter=4000')
    conn.execute('PRAGMA cipher_hmac_algorithm=HMAC_SHA1')
    conn.execute('PRAGMA cipher_kdf_algorithm=PBKDF2_HMAC_SHA512')
    conn.execute('SELECT count(*) FROM sqlite_master').fetchone()
    return conn
```

这里沿用实测成功的参数顺序，不把 SQLCipher 的默认参数当作 NTQQ 参数。`connect()` 返回连接，并不代表密钥验证通过；真正访问 `sqlite_master` 才会触发数据库页读取。[SQLCipher API 文档](https://www.zetetic.net/sqlcipher/sqlcipher-api/)说明了密钥设置、参数配置与校验接口的行为。

`mode=ro` 表示只读；`immutable=1` 额外告诉 SQLite 文件不会改变，并省略部分锁与变化检测。它只适用于已经固定的离线副本，不能把一个仍在写入的文件“变成”安全快照。[SQLite URI 文档](https://sqlite.org/uri.html)对此有明确说明。

剥离扩展头后，文件依然加密。为了避免名字造成误解，示例将它命名为 `source_payload.encrypted.db`，把真正导出的明文单会话库命名为 `chat_raw.sqlite`。

## 0x09 按会话筛选：同时考虑 QQ 号和 UID

读取表结构后，本次目标涉及以下几张表：

| 表 | 用途 |
| --- | --- |
| `c2c_msg_table` | 私聊消息 |
| `c2c_temp_msg_table` | 临时私聊消息，单独检查是否有目标记录 |
| `nt_uid_mapping_table` | 将数字 QQ 号与库中的 UID 表示关联 |

关键字段如下。解释依据是本次读取结果及上游字段定义，其他版本应先核对实际 schema。

| 字段号 | 本次用途 |
| --- | --- |
| `40001` | 消息 ID |
| `40050` | 时间戳 |
| `40013` | 方向字段 |
| `40020` / `40033` | 发送者 UID / QQ 号 |
| `40021` / `40030` | 会话对象 UID / QQ 号 |
| `40011` | 消息类型 |
| `40800` | 消息正文 Protobuf BLOB |

先查询 `nt_uid_mapping_table` 中目标 QQ 号对应的映射，再构造参数化条件：

```sql
WHERE [40030] = ?
   OR [40021] IN (?, ...)
```

这里的 `...` 表示按 UID 候选数量生成占位符，并不是直接执行的 SQL。筛选目标是“与这个联系人的会话”，因此使用会话对象字段。仅按发送者筛选，会把自己发给对方的消息遗漏。

复制时使用完整原始行，保留未知列和 BLOB；之后再生成解释过的 JSON。这样即使当前解析器不能处理某种消息，也不必重新访问原始账号数据库。

## 0x0A Protobuf 解析：成功、回退与未解释数据都要保留

本次复用了上游 `msgdb.c2c.parser.parse_row()` 与 `parse_40800()`。加载模块时遇到过一个独立于数据库的问题：系统中已有的 Protobuf runtime 与仓库生成代码的版本不匹配。

处理方法是查看生成文件中的 `Protobuf Python Version` 和版本检查代码，然后在隔离环境中安装匹配版本。这次生成代码使用 7.34.1；没有通过删除版本检查来绕开错误。

消息解析也不是非成功即失败。输出中保留以下状态：

| 状态 | 含义 |
| --- | --- |
| `typed` | 可按当前 Protobuf 模型解析，不等于所有业务字段均已解释 |
| `wire_fallback` | 模型解析失败，但底层 wire 结构仍可读取 |
| `invalid` | 模型和基础 wire 解析均失败 |
| `null` | 没有正文 BLOB |
| `parser_error` | 后续内容转换发生异常，原始记录仍保留 |

对进入 fallback 的记录继续检查，发现了图片和图文消息。按上游已定义的字段号，可以恢复部分信息：

| Protobuf 字段号 | 本次读取的信息 |
| --- | --- |
| `40800` | 外层重复消息段 |
| `45002` | 段内容类型 |
| `45101` | UTF-8 文本 |
| `45402` | 文件名 |
| `45405` / `45406` | 文件大小 / 摘要字节 |
| `45411` / `45412` | 图片宽高 |
| `45812` | 本地路径 |

补充解析只解释有依据的字段。文本采用严格 UTF-8 解码，失败就保持未知，不使用 `errors='ignore'` 静默丢字，也不猜测所有二进制字段都是文本。完整 BLOB 在原始单会话库中保留，示例的 fallback JSON 还保存正文十六进制，供将来重新解析。

这些补充结果继续标记为部分解析，不计为模型解析成功。图片元数据和本地路径也不等于图片本身；本文流程没有下载或复制附件。

## 0x0B 用通用示例执行完整导出

配套的 [qq_chat_export_example.py](/downloads/code/qq-chat-offline-extraction/qq_chat_export_example.py) 将上述步骤整理成一个通用脚本，没有写入实际账号、密钥或本机绝对路径。

准备好完整原始库快照和上游源码后运行：

```powershell
& .\.venv\Scripts\python.exe .\qq_chat_export_example.py `
  --db .\private_work\snapshot\nt_msg.db `
  --upstream .\sources\nt_msg_db_util `
  --out .\private_work\selected_chat
```

脚本会询问目标联系人 QQ 号，并隐藏输入数据库密钥。输出目录必须尚不存在，防止把这次结果混入上次导出。

它只接受带 `QQ_NT DB` 标记的原始库快照，不会把 `MSG0` 备份当成支持的输入。示例遇到数据库读取错误会停止并记录失败，不会静默跳过数据；消息内容解析失败则保留原始行，并记录对应解析状态。

输出文件的职责分别是：

| 文件 | 内容 |
| --- | --- |
| `source_payload.encrypted.db` | 剥离扩展头后的加密工作副本 |
| `chat_raw.sqlite` | 目标私聊原始记录和目标 UID 映射 |
| `messages.jsonl` | 每行一条消息，包含时间、来源表、解析状态和可解释内容 |
| `chat.txt` | 按时间排列的阅读版本，非文本内容以类型提示 |
| `export_report.json` | 完成状态、数量、解析统计、输出校验和文件哈希 |

这个公开示例整理自实测处理逻辑，并以合成数据验证；它没有再次访问真实账号数据库。上游字段定义变化时，示例也需要相应调整。它不实现群聊导出、附件归档或 `.bak` 专用解密。

## 0x0C 怎样确认导出结果可用

这次校验重点放在数据关系，而不只看程序是否退出成功：

```text
副本中匹配的记录数 = 单会话 SQLite 记录数 = JSONL 消息数
导出数据库 integrity_check = ok
目标 QQ 号冲突数 = 0
按时间戳、消息 ID 排序的检查 = 通过
输入快照导出前后保持一致
```

原始表中的消息 ID、时间和 BLOB 都保留在单会话库中。解析不完整的记录不会因为缺少 `text` 就从结果中消失，JSON 仍然包含该条记录及状态。

三个不同层次的数量也要区分：记录数、包含文字的记录数、完整解释所有业务字段的记录数，不能互相替代。

## 0x0D 整库检查仍有一处未解决的问题

完整加密副本曾在约 1 GiB 附近的一页报 HMAC 异常，检查发现该页全零；整库 `quick_check` 也没有通过。

SQLite 文件格式确实有锁字节页这一特殊区域，约在 1 GiB 位置，但仅凭位置相近不足以确定这里的异常就是锁页行为。扩展头、QQ 自身实现和工具兼容性也可能影响解释。[SQLite 文件格式文档](https://sqlite.org/fileformat2.html#the_lock_byte_page)可以作为进一步分析的依据，本次没有得出确定原因。

因此，不能将“目标会话导出成功”写成“整个原始数据库完好”。本次能确认的范围是：选定会话的匹配记录全部读出，复制时没有跳过行，重新生成的单会话数据库通过完整性检查。

也没有为了让检查变绿而删除全零页、关闭 HMAC 校验，或修改 QQ 的原始数据库。

## 0x0E 这次排查得到的结论

| 检查项 | 本次结果 |
| --- | --- |
| 官方备份容器能否读取 | 可以 |
| 官方备份内部库能否用已知方法解密 | 未成功，具体差异尚未查明 |
| 提供的密钥对本机原始库是否有效 | 有效，已通过实际数据库读取验证 |
| 目标会话能否从原始库副本提取 | 可以，匹配数量与输出数量一致 |
| 单会话导出数据库是否通过完整性检查 | 通过 |
| 是否所有消息类型都完整解释 | 没有；保留了未知字段与解析状态 |
| 是否完成附件归档 | 没有，本次只处理数据库与元数据 |
| 是否能保证所有版本适用、零风控 | 不能作这样的保证 |

这次能继续推进，关键在于把“容器能读取”“密钥能打开原始库”“消息字段能解析”分别验证。对目标会话先做完整字段复制，再生成阅读版本，也让解析器的能力边界不会变成原始记录的丢失。

## 0x0F 公开本文时的文件范围

可公开的材料只有本文和通用示例代码。`private_work/`、实际脚本配置、数据库、JSONL、聊天文本、运行报告及调试日志都属于私有材料。

特别是 JSON 中的 UID、发送者、消息时间、图片文件名、本地路径和媒体 URL，以及 BLOB 的十六进制表示，都可能包含个人信息。把二进制转成十六进制不是匿名化；记录精确数量、时间范围和私有文件哈希也没有出现在这份公开稿中。

文中保留的都是格式标记、算法参数、字段编号、通用代码与公开项目链接，可将它们和自己的私有导出数据分开维护。
