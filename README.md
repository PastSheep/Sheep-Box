# Sheep Box

Sheep Box 项目。

## 环境要求

- Python 3.9+
- 虚拟环境：`python -m venv .venv`

## 安装

```bash
# 激活虚拟环境（Windows）
.venv\Scripts\activate

# 安装开发依赖（含 black / ruff / mypy / pre-commit / pytest）
pip install -e ".[dev]"

# 安装 pre-commit 钩子
pre-commit install
```

## 目录结构

```text
config/    配置文件、环境配置
common/    公共工具、常量、异常、通用方法
service/   核心业务逻辑
models/    数据模型、结构体、ORM 模型
api/       接口入口
tests/     单元测试、集成测试
main.py    项目启动入口
```

## 开发规范

开发请严格遵守 `docs/开发规范/` 下的三份规范：

- Python 项目编程规范
- 项目 Git 协作规范
- 项目日志 Logger 约定规范
