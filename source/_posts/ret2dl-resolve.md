---
title: ret2dl_resolve 无输出环境下的动态链接劫持
date: 2026-05-10 21:30:00
categories:
  - pwn
tags:
  - ret2dl_resolve
  - 动态链接
  - SROP
  - GOT表
  - 64位
---

> 64位 ret2dl_resolve 与无输出环境下的生存技巧

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 架构 | 64-bit (amd64) |
| NX | Enabled（栈不可执行） |
| PIE | Disabled（代码段地址固定 `0x400000`） |
| RELRO | Partial RELRO（GOT 表和 Link Map 可写） |
| Libc | libc-2.27.so |

**核心困境**：整个程序只有 `read` 函数，没有 `puts`、`printf` 或 `write`。传统 `ret2libc` 需要先泄露基址，但无输出函数无法打印任何 GOT 表地址。

```c
int __cdecl main(int argc, const char **argv, const char **envp) {
  char buf[256]; 
  return read(0, buf, 4096); // 漏洞点：严重的栈溢出
}
```

## 0x02 核心技术思路

### 思路一：ret2dl_resolve（题目意图）

动态链接程序在第一次调用函数时，会通过 `_dl_runtime_resolve` 寻找真实地址。

**原理**：伪造动态链接所需的重定位表项（`Elf64_Rela`）、符号项（`Elf64_Sym`）和字符串（`.dynstr`）。

**64 位特有的坑**：
1. **Versym 索引越界**：64位解析器会检查版本号表（`.gnu.version`），伪造的符号索引太大会导致 Segfault
2. **对齐要求**：`Elf64_Sym` 必须 24 字节对齐

**解法**：使用 **Fake Link Map**，手动在 BSS 段伪造整个 `link_map` 结构体，将字符串表指针（`DT_STRTAB`）指向我们控制的区域。

### 思路二：SROP (Sigreturn Oriented Programming)

当常规 ROP 链因缺乏 Gadget（尤其是控制 `rdx` 的 Gadget）而无法执行 `execve` 时的杀手锏。

**原理**：利用系统调用 `rt_sigreturn`（系统调用号 `15`）从栈上恢复所有寄存器的状态。

**执行步骤**：
1. 利用 `read` 函数的返回值控制 `RAX = 15`
2. 寻找 `syscall` 指令
3. 在栈上布置 `SigreturnFrame`，精确设置 `RDI="/bin/sh"`, `RAX=59` (execve), `RIP=syscall`

**优势**：不需要泄露地址，只需找到 `syscall` 指令。

### 思路三：GOT 表部分覆盖 (Partial Overwrite)

**原理**：利用 `read@GOT` 的低位一字节修改。`read` 函数内部通常包含 `syscall` 指令，将 `read@GOT` 的最后一字节改为 `syscall` 的偏移，配合 `RAX` 控制（读取 15 或 59 字节），可直接执行 `execve` 或 `sigreturn`。

## 0x03 关键代码

### 64位手工布局 dl_resolve

```python
base_stage = elf.bss() + 0x200
dlresolve = Ret2dlresolvePayload(elf, symbol="system", args=["/bin/sh"], data_addr=base_stage)

rop = ROP(elf)
rop.read(0, dlresolve.data_addr, 0x100)
rop.ret2dlresolve(dlresolve)
```

### 构造 SROP 框架

```python
frame = SigreturnFrame()
frame.rax = constants.SYS_execve
frame.rdi = bin_sh_addr
frame.rsi = 0
frame.rdx = 0
frame.rip = syscall_addr

# 触发：先控制 RAX=15，再执行 syscall
```

## 0x04 经验总结与避坑指南

1. **ConnectionAbortedError / EOF**：远程程序 Segfault 时连接会异常断开，常见原因：栈没对齐、versym 越界、Payload 字节数没填满导致 `read` 卡住
2. **偏移计算**：`buf` 距离 `rbp` 为 `0x100`，覆盖 `rbp` (8 字节) 后即为返回地址，**Total Padding = 264 bytes**
3. **万能对齐**：在 ROP 链执行 `system` 之前，尝试先塞入一个单纯的 `ret` 指令地址来平摊栈帧

## 0x05 核心考点

- **ret2dl_resolve**：伪造动态链接结构体劫持函数解析
- **SROP**：利用 `sigreturn` 系统调用一次性恢复所有寄存器
- **无输出环境生存**：当没有泄露手段时的多种绕过思路
- **Fake Link Map**：手动伪造 `link_map` 绕过索引限制
