---
title: easyre IDA 入门签到题
date: 2026-05-12 16:57:00
categories:
  - reverse
tags:
  - 签到题
  - IDA
  - 入门
---

> 逆向签到题 | IDA 反编译直接读取 Flag

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 题目类型 | 逆向入门 / 签到题 |
| 工具 | IDA Pro |
| 核心考点 | IDA 基本使用、反编译伪代码阅读 |

## 0x02 逆向分析

使用 IDA 打开 `easyre.exe`，直接查看 `main` 函数的反编译伪代码：

```c
int __cdecl main(int argc, const char **argv, const char **envp)
{
  int b; // [rsp+28h] [rbp-8h] BYREF
  int a; // [rsp+2Ch] [rbp-4h] BYREF

  _main();
  scanf("%d%d", &a, &b);
  if ( a == b )
    printf("flag{this_Is_a_EaSyRe}");
  else
    printf("sorry,you can't get flag");
  return 0;
}
```

程序逻辑极其简单：读取两个整数 `a` 和 `b`，如果两者相等则直接输出 Flag。

## 0x03 解题思路

程序本身已经硬编码了 Flag，不需要真正输入任何东西。直接在 IDA 的反编译结果中就能看到 `printf("flag{this_Is_a_EaSyRe}")`。

如果需要通过运行程序获取，输入两个相同的整数即可，例如 `1 1`。

## 0x04 Flag

```
flag{this_Is_a_EaSyRe}
```

## 0x05 核心考点

- **IDA 基本操作**：加载 PE 文件，F5 反编译查看伪代码
- **伪代码阅读**：理解 `scanf`、条件判断、`printf` 的基本逻辑
- **签到题心态**：逆向题不一定要运行程序，IDA 中直接读取即可
