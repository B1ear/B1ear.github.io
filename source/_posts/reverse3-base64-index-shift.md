---
title: reverse3 Base64 与索引移位双层加密
date: 2026-05-12 18:17:00
categories:
  - reverse
tags:
  - Base64
  - 逆向解密
  - 双层加密
  - Python脚本
---

> BUUCTF reverse3 | Base64 编码叠加索引移位混淆，逆向还原明文 Flag

## 0x01 题目环境

| 项目 | 内容 |
|------|------|
| 题目名称 | BUUCTF reverse3 |
| 架构 | 32位 Windows PE |
| 工具 | IDA Pro、Python |
| 核心考点 | Base64 编码识别、逐字符移位加密、逆向解密脚本编写 |

## 0x02 逆向分析

### 核心伪代码

```c
int __cdecl main_0(int argc, const char **argv, const char **envp)
{
    size_t v3;
    const char *v4;
    size_t v5;
    signed int j;
    int i;
    signed int v11;
    char Destination[108];
    char Str[28];
    char v14[8];

    // 初始化 Destination 数组
    for ( i = 0; i < 100; ++i )
    {
        if ( (unsigned int)i >= 0x64 )
            j____report_rangecheckfailure();
        Destination[i] = 0;
    }

    // 获取用户输入
    sub_41132F("please enter the flag:", v7);
    sub_411375("%20s", (char)Str);
    v3 = j_strlen(Str);

    // 第一层加密：Base64 编码
    v4 = (const char *)sub_4110BE(Str, v3, v14);
    strncpy(Destination, v4, 0x28u);
    v11 = j_strlen(Destination);

    // 第二层加密：逐字符加索引
    for ( j = 0; j < v11; ++j )
        Destination[j] += j;

    // 校验比对
    v5 = j_strlen(Destination);
    if ( !strncmp(Destination, Str2, v5) )
        sub_41132F("rigth flag!\n", v8);
    else
        sub_41132F("wrong flag!\n", v8);

    return 0;
}
```

### 正向加密逻辑

程序对用户输入进行了两层加密：

1. **第一层（Base64 编码）**：调用 `sub_4110BE(Str, v3, v14)`，根据参数特征（明文、长度、输出缓冲区）判断这是一个 Base64 编码函数。编码后的字符串被拷贝到 `Destination`。

2. **第二层（索引移位）**：通过循环 `Destination[j] += j`，将每个字符的 ASCII 值加上其所在索引位置。这是一种简单的线性混淆。

3. **最终比对**：混淆后的 `Destination` 与全局变量 `Str2` 比较。

### 提取目标密文

在 IDA 的 `.data` 段中找到 `Str2` 的值：

```
.data:0041A034  Str2 db 'e3nifIH9b_C@n@dH',0
```

## 0x03 逆向解密推导

解密需要逆向执行两层加密：

```
目标密文 Str2 → 逐字符减去索引（逆第二层）→ Base64 解码（逆第一层）→ 明文 Flag
```

## 0x04 解密脚本

```python
#!/usr/bin/env python3
import base64

# 从 IDA .data 段提取的 Str2 数据
str2_data = b"e3nifIH9b_C@n@dH"

def decrypt(target_bytes):
    recovered_encoded_bytes = bytearray()

    # 逆向第二层：Destination[j] += j → target[j] -= j
    for j in range(len(target_bytes)):
        original_char = (target_bytes[j] - j) & 0xFF
        recovered_encoded_bytes.append(original_char)

    print(f"[*] 还原出的 Base64 字符串: {recovered_encoded_bytes.decode('utf-8')}")

    # 逆向第一层：Base64 解码
    try:
        flag = base64.b64decode(recovered_encoded_bytes).decode('utf-8')
        print(f"[+] Flag: {flag}")
    except Exception as e:
        print(f"[-] 解码失败: {e}")

if __name__ == "__main__":
    decrypt(str2_data)
```

## 0x05 执行结果

```
[*] 还原出的 Base64 字符串: e2lfbDB2ZV95b3V9
[+] Flag: i_l0ve_you
```

## 0x06 Flag

```
flag{i_l0ve_you}
```

## 0x07 核心考点

- **Base64 识别**：根据函数参数特征（明文、长度、输出缓冲区）判断编码类型
- **逐字符移位**：`Destination[j] += j` 是线性混淆，逆运算为 `target[j] -= j`
- **按位与 0xFF**：减法后需确保结果在 0~255 范围内，防止溢出
- **多层加密逆向**：从最后一层开始逐层还原，先逆移位再逆编码
- **数据段提取**：在 IDA `.data` 段中定位比较用的目标字符串
