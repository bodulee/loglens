<div align="center">

# LogLens

**一条命令，看懂你的 Web 访问日志。**

A dependency-free Python CLI for local Nginx / Apache access log analysis.

[![Tests](https://github.com/bodulee/loglens/actions/workflows/tests.yml/badge.svg)](https://github.com/bodulee/loglens/actions/workflows/tests.yml)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

LogLens 帮你快速回答：哪些路径访问最多？4xx / 5xx 占多少？哪些来源请求最频繁？已记录的响应流量有多少？

适用于本地排查 Nginx / Apache **Common / Combined 格式**的访问日志。无需部署服务，无需安装第三方运行依赖；日志始终留在本机。

## 30 秒上手

需要 Python 3.10 或更新版本。在 Linux / macOS 终端中执行：

```bash
git clone https://github.com/bodulee/loglens.git
cd loglens
python3 -m loglens examples/access.log
```

Windows 将 `python3` 换成 `python` 即可。示例使用合成日志和文档专用 IP 地址。

输出摘要：

```text
LogLens - HTTP access log report
================================
Requests: 5
Errors (4xx/5xx): 2 (40.00%)
Response bytes (known): 170
Unknown response sizes: 1
Unique clients: 3
Lines: 5 | Blank: 0 | Malformed: 0
```

随后列出状态码、请求方法、热门路径和访问来源；示例中的 `/search` 会合并为 2 次访问。

## 常用命令

```bash
# 分析当前日志，显示前 10 名
python3 -m loglens /var/log/nginx/access.log

# 合并分析当前日志与 gzip 轮转日志
python3 -m loglens access.log access.log.1.gz --top 20

# 从管道读取；用 - 显式指定标准输入
cat access.log | python3 -m loglens -

# 导出 JSON，供脚本或其他工具使用
python3 -m loglens access.log --json > report.json

# 区分 /search?q=linux 与 /search?q=python
python3 -m loglens access.log --keep-query

# 查看帮助
python3 -m loglens --help
```

如果希望在任意目录使用 `loglens` 命令，可在虚拟环境中安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
loglens examples/access.log
```

Windows PowerShell 的激活命令为 `.\.venv\Scripts\Activate.ps1`。安装阶段需要 setuptools 构建工具；从源码直接执行 `python -m loglens` 不需要安装任何依赖。本项目尚未发布到 PyPI。

## 功能与统计口径

| 项目 | 行为 |
| --- | --- |
| 日志输入 | 一个或多个 UTF-8 文件、`.gz` 文件、标准输入；支持 UTF-8 BOM |
| 请求统计 | 有效记录数、状态码分布、请求方法分布 |
| 错误率 | 有效记录中，HTTP 400–599 的比例 |
| 响应大小 | 累加日志中的字节字段；`-` 单独计为未知大小，不估算流量 |
| 热门路径 | 默认移除 `?` 及后面的查询字符串；`--keep-query` 可保留 |
| 来源统计 | 按日志首字段统计，支持 IPv4、IPv6 或主机名 |
| 排行顺序 | 次数降序；次数相同时按字段值排序，保证结果稳定 |
| 异常行 | 分别统计空行和不支持的记录；有效记录仍参与分析 |
| 安全输出 | 文本报告转义控制字符；JSON 使用标准转义 |

JSON 包含 `requests`、`errors`、`error_rate_percent`、`bytes_sent`、`unknown_size_requests`、`unique_clients`、`status_codes`、`methods`、`top_paths`、`top_clients` 和行数统计。排行榜每项为 `{"value": "/path", "count": 3}`。

退出码可用于 Shell 脚本：

- `0`：读取成功；空文件也会输出零值报告。混合有效记录与异常行时，请检查 `malformed_lines`。
- `1`：输入含异常行，但没有任何有效记录；仍输出报告。
- `2`：参数错误、文件不可读、UTF-8 解码失败或 gzip 损坏；不输出部分统计结果。

## 支持范围

支持标准 Common 格式，以及追加 Referer、User-Agent 两个引号字段的 Combined 格式；允许字段内的反斜杠转义。请求字段为 `"-"` 的记录仍计入状态统计，路径和方法显示为 `-`。

自定义 JSON 日志、额外的日志前缀或后缀、错误日志、缺少 HTTP 版本的请求行暂不支持，会计入异常行。时间字段仅匹配标准外形，不校验日历日期，也不参与统计。

工具逐行读取，但会保存不同路径和来源的计数；内存消耗随唯一值数量增长，`--top` 仅限制显示条数。多个输入文件按原样累加，不去重。来源字段可能是代理地址，不一定代表独立访客。响应大小沿用日志配置中的字段，不代表包含全部协议开销的网络流量。

所有处理均在本地完成；导出的报告仍可能包含 IP 和路径，`--keep-query` 还会包含查询参数。工具只读取日志，不修改或删除文件。

格式参考：[Nginx log module](https://nginx.org/en/docs/http/ngx_http_log_module.html)、[Apache access logs](https://httpd.apache.org/docs/2.4/logs.html#accesslog)。

## 开发与测试

```bash
python3 -m unittest discover -s tests -v
```

测试使用真实临时文件和 CLI 子进程，覆盖统计、查询参数、压缩日志、IPv6、异常输入及安全输出。GitHub Actions 在 Linux / Windows 和 Python 3.10 / 3.12 上执行测试，并验证安装后的命令入口。

```text
loglens/
├── loglens/       # 日志解析、统计与命令行入口
├── tests/         # CLI 集成测试
├── examples/      # 可直接运行的示例日志
└── pyproject.toml # 项目配置
```

## License

[MIT](LICENSE) · Built by [bodulee](https://github.com/bodulee)
