---
title: luck_guy GDB 动态调试绕过随机数陷阱
date: 2026-05-12 23:20:00
categories:
  - reverse
tags:
  - GDB
  - 动态调试
  - 随机数
  - 小端序
  - 逆向解密
---

> [GXYCTF2019] luck_guy | GDB 手动劫持寄存器，绕过 rand() 执行流陷阱

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 题目名称 | [GXYCTF2019] luck_guy |
| 架构 | 64位 Linux ELF |
| 工具 | IDA Pro、GDB |
| 核心考点 | GDB 动态调试、寄存器劫持、小端序转换、随机数陷阱绕过 |

## 0x02 逆向分析

### main 函数

```c
int __cdecl main(int argc, const char **argv, const char **envp)
{
    unsigned int v4;
    unsigned __int64 v5;

    v5 = __readfsqword(0x28u);
    welcome(argc, argv, envp);
    puts("_________________");
    puts("try to patch me and find flag");
    v4 = 0;
    puts("please input a lucky number");
    __isoc99_scanf("%d", &v4);
    patch_me(v4);
    puts("OK,see you again");
    return 0;
}
```

### patch_me 函数

```c
int __fastcall patch_me(int a1)
{
    if ( a1 % 2 == 1 )
        return puts("just finished");  // 奇数：直接退出
    else
        return get_flag();             // 偶数：进入 get_flag
}
```

输入任意偶数即可进入 `get_flag()` 分支。

### get_flag 函数（核心）

```c
unsigned __int64 get_flag()
{
    v0 = time(0LL);
    srand(v0);
    for ( i = 0; i <= 4; ++i )
    {
        switch ( rand() % 200 )
        {
            case 1:  // 拼接 f1 + f2 并打印
                puts("OK, it's flag:");
                strcat((char *)&s, f1);
                strcat((char *)&s, &f2);
                printf("%s", (const char *)&s);
                break;
            case 4:  // 初始化 f2 密文
                s = 0x7F666F6067756369LL;
                v5 = 0;
                strcat(&f2, (const char *)&s);
                break;
            case 5:  // 解密 f2
                for ( j = 0; j <= 7; ++j )
                {
                    if ( j % 2 == 1 )
                        *(&f2 + j) -= 2;
                    else
                        --*(&f2 + j);
                }
                break;
            default:
                puts("emmm,you can't find flag 23333");
                break;
        }
    }
}
```

### 陷阱分析

要输出完整的 Flag，循环 5 次中必须依次命中 `case 4 → case 5 → case 1`。每次 `rand() % 200` 的结果是随机的，自然运行命中的概率几乎为零。

## 0x03 解题方案

提供两种解法：GDB 动态调试法和静态推演法。

### 方案一：GDB 动态调试（推荐）

#### Step 1：在 IDA 中定位断点地址

找到 `rand() % 200` 计算完成后、写入内存前的汇编指令：

```asm
sub     ecx, eax            ; 计算余数
mov     eax, ecx            ; 余数放入 eax
mov     [rbp+var_34], eax   ; 【断点位置】写入内存
cmp     [rbp+var_34], 5     ; 判断是否大于 5
ja      def_400843          ; 跳转至 default
```

最佳断点位置：`mov [rbp+var_34], eax`（地址 `0x40082b`），在余数写入内存的前一刻拦截。

#### Step 2：GDB 操作流程

```bash
# 启动 GDB 并下断点
gdb ./luck_guy
(gdb) b *0x40082b

# 运行程序，输入偶数进入 get_flag
(gdb) run
# 输入: 2

# 第一轮：引导到 case 4（初始化 f2）
(gdb) set $eax = 4
(gdb) c

# 第二轮：引导到 case 5（解密 f2）
(gdb) set $eax = 5
(gdb) c

# 第三轮：引导到 case 1（打印 Flag）
(gdb) set $eax = 1
(gdb) c

# 删除断点，让程序跑完剩余循环以刷新输出缓冲区
(gdb) d
Delete all breakpoints? (y or n) y
(gdb) c
```

**输出**：`GXY{do_not_hate_me}`

#### 原理解析

在 x86 架构中，`eax` 存放计算结果。在 `mov [rbp+var_34], eax` 之前修改 `eax` 的值，程序后续的 `cmp` 和 `switch` 跳转表就会按修改后的值执行。

关于输出缓冲区：`printf` 在遇到 `\n` 或程序正常退出时才将内容推送到终端。如果程序被断点挂起，缓冲区未刷新，需要删除断点让程序正常跑完。

### 方案二：静态推演

不使用 GDB，直接提取 `case 4` 和 `case 5` 的逻辑手动计算。

#### Step 1：小端序转换（Case 4）

`case 4` 中赋值 `s = 0x7F666F6067756369LL`，x86_64 小端序存储，按字节反转：

| 字节 | 0x69 | 0x63 | 0x75 | 0x67 | 0x60 | 0x6F | 0x66 | 0x7F |
|------|------|------|------|------|------|------|------|------|
| ASCII | `i` | `c` | `u` | `g` | `` ` `` | `o` | `f` | DEL |

#### Step 2：解密算法推演（Case 5）

规则：偶数索引 `-1`，奇数索引 `-2`。

| 索引 | 原始值 | 操作 | 结果 | 字符 |
|------|--------|------|------|------|
| 0 | 0x69 | -1 | 0x68 | `h` |
| 1 | 0x63 | -2 | 0x61 | `a` |
| 2 | 0x75 | -1 | 0x74 | `t` |
| 3 | 0x67 | -2 | 0x65 | `e` |
| 4 | 0x60 | -1 | 0x5F | `_` |
| 5 | 0x6F | -2 | 0x6D | `m` |
| 6 | 0x66 | -1 | 0x65 | `e` |
| 7 | 0x7F | -2 | 0x7D | `}` |

解密结果：`hate_me}`

#### Step 3：提取全局变量 f1

在 IDA `.data` 段中找到 `f1`：`GXY{do_not_`

拼接 `f1` + 解密后的 `f2`：`GXY{do_not_` + `hate_me}`

## 0x04 Flag

```
GXY{do_not_hate_me}
```

## 0x05 核心考点

- **GDB 寄存器劫持**：`set $eax = N` 修改计算结果，强行引导 switch 分支
- **断点选择**：不能下在 `cmp` 处，必须在 `mov [mem], eax` 处拦截
- **输出缓冲区**：`printf` 无 `\n` 时内容被缓冲，需程序正常退出才刷新
- **小端序转换**：64 位整型按字节反转得到正确的字符序列
- **随机数陷阱**：`rand() % 200` 构造极低概率执行流，阻挠动态调试
- **编译器除法优化**：`% 200` 被优化为魔数乘法（`0x51EB851F`），需找到真正的余数计算位置
