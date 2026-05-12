---
title: reverse2 fork 多进程字符串替换
date: 2026-05-12 17:36:00
categories:
  - reverse
tags:
  - fork
  - 字符串替换
  - 多进程
  - ASCII
---

> BUUCTF reverse2 | fork 进程隔离陷阱与字符串动态替换

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 题目名称 | BUUCTF reverse2 |
| 架构 | 64位 Linux ELF |
| 核心考点 | fork 多进程、字符串替换、Copy-on-Write 机制 |

## 0x02 逆向分析

### 核心伪代码

```c
int __cdecl main(int argc, const char **argv, const char **envp)
{
    int stat_loc;
    int i;
    __pid_t pid;
    char s2[24];
    unsigned __int64 v8;

    v8 = __readfsqword(0x28u);
    pid = fork();

    if ( pid )
    {
        // 父进程：等待子进程结束
        waitpid(pid, &stat_loc, 0);
    }
    else
    {
        // 子进程：替换字符串中的 'i' 和 'r' 为 '1'
        for ( i = 0; i <= strlen(&flag); ++i )
        {
            if ( *(&flag + i) == 105 || *(&flag + i) == 114 )
                *(&flag + i) = 49;
        }
    }

    // 两个进程都会执行以下代码
    printf("input the flag:");
    __isoc99_scanf("%20s", s2);

    if ( !strcmp(&flag, s2) )
        return puts("this is the right flag!");
    else
        return puts("wrong flag!");
}
```

### 静态数据提取

在 IDA 中双击全局变量 `flag`，在 `.data` 段找到原始字符串：

```
.data:0000000000601080 flag db 7Bh                  ; ASCII: '{'
.data:0000000000601081 aHackingForFun db 'hacking_for_fun}',0
```

拼接后得到原始字符串：`{hacking_for_fun}`

### 逻辑分析与避坑

#### 陷阱：Linux 的 Copy-on-Write 机制

在真实的 Linux 环境下，`fork()` 会让子进程获得父进程数据空间、堆和栈的**副本**。子进程在 `else` 分支中把 `'i'` 和 `'r'` 替换为 `'1'` 的操作，**仅发生在其独立的内存副本中**。

当子进程结束后，父进程被 `waitpid` 唤醒继续执行时，父进程内存中的 `flag` 变量依然是未经修改的 `{hacking_for_fun}`。

因此，如果严格按系统机制分析，父进程的 `strcmp` 比较的是原始字符串，输入原始字符串即可。

#### 破局：揣摩出题人意图

在基础 CTF 逆向题中，出题人写这段代码的本意是考察"字符串的动态替换/加密逻辑"，而忽略了 `fork` 的多进程隔离特性。

因此，解题应顺着子进程的 `for` 循环逻辑，手动完成字符串替换。

## 0x03 Flag 推导

将 `{hacking_for_fun}` 中的 `i` 和 `r` 全部替换为 `1`：

- **原始字符串**：`{hacking_for_fun}`
- `i` → `1`：`{hack1ng_for_fun}`
- `r` → `1`：`{hack1ng_fo1_fun}`

结合平台提示"flag 请包上 flag{} 提交"。

## 0x04 Flag

```
flag{hack1ng_fo1_fun}
```

## 0x05 核心考点

- **fork 多进程**：子进程获得父进程内存的副本，修改不会影响父进程（Copy-on-Write）
- **出题人意图 vs 系统机制**：CTF 题有时需要站在出题人的角度思考，而非严格按系统行为分析
- **字符串替换**：ASCII 码 `105 = 'i'`，`114 = 'r'`，`49 = '1'`
- **灵活思维**：当"标准答案"不被接受时，换个角度重新审视代码
