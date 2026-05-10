---
title: test_your_nc Pwn 签到题
date: 2026-05-09 19:24:00
categories:
  - pwn
tags:
  - 签到题
  - 入门
  - pwntools
  - system
---

> CTF 签到题 | 连接即给 Shell，熟悉 pwntools 基本流程

## 0x01 题目背景

这是一道极度简化的 Pwn 题目，作为 CTF 比赛中的"签到题"出现。核心目的在于测试选手是否掌握了基本的连接靶机能力，而非考察复杂的内存破坏漏洞。

## 0x02 逆向分析

使用 IDA 反编译 `main` 函数：

```asm
main proc near
push    rbp
mov     rbp, rsp
lea     rdi, command    ; 加载 "/bin/sh" 字符串地址
call    _system         ; 调用 system()
mov     eax, 0
pop     rbp
retn
main endp
```

**关键分析**：
- 64位 Linux (System V AMD64 ABI) 中，第一个参数通过 `rdi` 寄存器传递
- 程序将 `"/bin/sh"` 地址传入 `rdi`，直接调用 `system()`
- **没有任何漏洞**，程序本身就是合法的后门，运行即给 Shell

## 0x03 解题思路

程序内部已经准备好了 Shell，不需要：
- 计算偏移
- 构造 ROP 链
- 考虑保护机制（NX, Canary, PIE）

**唯一需要做的**：与远程服务器建立连接，接管 Shell，执行 `cat flag`。

## 0x04 Exploit 代码

```python
#!/usr/bin/env python3
from pwn import *

HOST = '127.0.0.1' 
PORT = 10000       

def exploit():
    log.info(f"Connecting to {HOST}:{PORT}...")
    io = remote(HOST, PORT)
    log.success("Shell obtained! Entering interactive mode...")
    io.interactive()

if __name__ == '__main__':
    exploit()
```

## 0x05 夺旗步骤

1. 运行脚本：`python3 exp.py`
2. 进入 `interactive` 模式
3. `ls` 查看文件列表
4. `cat flag` 读取 Flag

## 0x06 核心考点

- **pwntools 基础**：`remote()` 建立连接、`interactive()` 交互
- **system 函数调用**：理解 `rdi` 寄存器传参
- **签到题心态**：不要想复杂，连上就能拿分
