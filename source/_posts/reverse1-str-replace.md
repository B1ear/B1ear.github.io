---
title: reverse1 字符串替换逆向
date: 2026-05-12 17:10:00
categories:
  - reverse
tags:
  - 字符串替换
  - ASCII
  - IDA
  - 入门
---

> 逆向入门题 | 识别编译器干扰代码，分析 ASCII 字符替换算法

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 题目类型 | 逆向入门 |
| 工具 | IDA Pro |
| 核心考点 | 编译器特征识别、ASCII 码转换、字符串比对分析 |

## 0x02 逆向分析

### 寻找真正的入口

IDA 反编译得到的 `main` 函数被标记为 `// attributes: thunk`，这是一个跳转桩，仅将参数传递到真正的逻辑函数 `main_0`。因此需要直接分析 `main_0`。

### 识别编译器干扰代码

`main_0` 开头有一段看似异常的循环：

```c
v3 = &v7;
for ( i = 82i64; i; --i )
{
    *(_DWORD *)v3 = -858993460;
    v3 += 4;
}
```

十进制 `-858993460` 转换为十六进制是 `0xCCCCCCCC`。这是 Visual Studio (MSVC) 在 Debug 模式下的特征代码（`_RTC_INIT_STACK`），用于将未初始化的栈内存填充为 `0xCC`（即 `int 3` 断点指令的机器码）。其目的是检测未初始化变量的滥用和栈溢出。

**结论**：这段代码与题目逻辑无关，逆向分析时应直接忽略。

### 核心算法分析

```c
for ( j = 0; ; ++j )
{
    v10 = j;
    if ( j > j_strlen(Str2) )
        break;
    if ( Str2[j] == 111 )       // 111 = 'o'
        Str2[j] = 48;           // 48 = '0'
}
```

程序遍历全局字符串 `Str2`，将所有 ASCII 码为 `111`（字母 `'o'`）的字符替换为 ASCII 码 `48`（数字 `'0'`）。

### 验证逻辑

```c
sub_14001128F("%20s", Str1);      // 读取用户输入
v5 = j_strlen(Str2);
if ( !strncmp(Str1, Str2, v5) )   // 与替换后的 Str2 比较
    sub_1400111D1("this is the right flag!\n");
```

用户输入与**替换后的** `Str2` 进行比较，相等则输出正确提示。

### 提取原始数据

在 IDA 的 `.data` 段中找到 `Str2` 的初始值：

```
.data:000000014001C000  Str2 db '{hello_world}',0
```

## 0x03 Flag 推导

手动模拟替换过程：

- **原始字符串**：`{hello_world}`
- 替换第一个 `'o'`：`{hell0_world}`
- 替换第二个 `'o'`：`{hell0_w0rld}`

## 0x04 Flag

```
flag{hell0_w0rld}
```

## 0x05 核心考点

- **Thunk 函数识别**：`main` 为跳转桩，实际逻辑在 `main_0`
- **编译器特征**：`0xCCCCCCCC` 是 MSVC Debug 模式的栈初始化标记，应忽略
- **ASCII 码对照**：`111 = 'o'`，`48 = '0'`，需要熟悉常见 ASCII 值
- **数据段提取**：在 IDA `.data` 段中定位全局变量的初始值
