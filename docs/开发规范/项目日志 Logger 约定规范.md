# 项目日志 Logger 约定规范



## 1 总则



### 1.1 目的

统一项目日志打印、采集、配置、字段、级别、异常埋点的标准；避免日志杂乱、丢失堆栈、敏感信息泄露、无法检索排查等问题；统一代码评审日志相关检查项。

本规范与《Python 项目编程规范》配套，适用于项目内所有业务代码、脚本、测试代码。



### 1.2 适用范围

项目全部 Python 代码，包含接口层、服务层、模型层、定时任务、CLI 脚本；**不包含第三方库内部日志**。



### 1.3 核心原则

1. 可观测：日志用于故障排查、链路追踪、业务统计，不是调试草稿

2. 集中配置：模块只获取 logger，不私自创建 Handler、Formatter

3. 结构化优先：线上输出 JSON 格式，方便日志平台检索、过滤、告警

4. 安全：严禁打印敏感信息

5. 最小侵入：业务代码尽量简洁，日志配置收敛在项目入口



## 2 Logger 实例获取约定（强制）



### 2.1 模块标准写法

每个 Python 模块顶部固定写法：

```python

import logging

logger = logging.getLogger(__name__)

```

- 依靠 `__name__` 自动形成层级 logger，例如 `app.service.user`

- 同一个名称多次调用 `getLogger` 返回同一个实例，不需要全局传递 logger

- **业务模块、service、model、api 层，只获取 logger，不做 handler、formatter 配置**



### 2.2 禁止写法

- ❌ 直接使用 `logging.info() / logging.error()`（直接使用 root logger，无法分级管控）

- ❌ 模块内部执行 `logging.basicConfig()`、`logger.addHandler()`

- ❌ 每个函数内部重新 `getLogger("xxx")` 硬编码名称（破坏层级管理）



> 补充：如果是项目内公共基础库代码，建议增加 `NullHandler` 防止未配置时抛告警：

> ```python

> import logging

> logger = logging.getLogger(__name__)

> logger.addHandler(logging.NullHandler())

> ```



### 2.3 入口职责

只有项目启动入口（`main.py` / cli 入口）负责日志全局配置，优先使用 `logging.config.dictConfig`。



## 3 日志级别使用约定（严格对齐）

固定 5 级，全项目统一理解：

- **DEBUG(10)**：调试信息、中间变量、入参出参详情；**生产环境默认关闭**，仅开发/联调开启

- **INFO(20)**：正常里程碑事件：服务启动、配置加载完成、任务开始/结束、用户正常登录、提交业务单据等；**线上默认主级别**

- **WARNING(30)**：程序可以继续运行，但存在非预期情况：重试触发、配置降级、资源接近阈值、收到兼容格式的脏数据

- **ERROR(40)**：单次业务操作失败，整体服务仍可继续运行：第三方调用失败、单条数据处理失败、单次请求校验失败

- **CRITICAL(50)**：核心依赖故障，进程/服务难以继续提供服务：数据库连接失败、核心配置缺失、基础依赖初始化失败



> 环境默认级别约定：

> - 开发环境：`DEBUG`

> - 测试环境：`INFO`

> - 生产环境：`INFO`



## 4 日志消息与格式化约定



### 4.1 两种写法选择

1. 标准库原生延迟格式化（推荐，性能更好，级别不命中时不执行格式化）

```python

logger.info("user login success, user_id=%s", user_id)

```

2. f-string：仅简单场景组内允许；复杂对象、高频路径优先上面占位写法。



> 禁止：为了打印日志，提前执行高开销序列化（如 json.dumps 大对象放到日志参数）。



### 4.2 结构化字段 extra（线上必备）

所有业务日志，关键上下文统一放到 `extra`，而不是塞在 message 文本里，方便日志平台检索：

```python

logger.info(

 "user_login_success",

 extra={

 "trace_id": trace_id,

 "user_id": user_id,

 "client_ip": client_ip

 }

)

```

约定：

- message 尽量是稳定事件名称（用于告警匹配）；变量放 extra

- extra 的 key 不能和 LogRecord 内置字段冲突：`asctime, levelname, name, lineno, msg, exc_info` 等

- 全项目统一字段命名：`trace_id、request_id、user_id、task_id、biz_id`，使用下划线命名



## 5 异常日志规范（重点红线）



✅ 捕获异常优先使用 `logger.exception("事件描述")`，自动带上堆栈，固定为 ERROR 级别：

```python

try:

 do_biz()

except Exception:

 logger.exception("handle user task failed")

```

等价于：

```python

logger.error("handle user task failed", exc_info=True)

```



✅ 如果异常属于警告，不应该打 ERROR，手动传入 exc_info：

```python

try:

 do_optional()

except ValueError:

 logger.warning("optional config parse warn", exc_info=True)

```



❌ 禁止写法：

```python

# 只打印异常文本，丢失堆栈，线上无法排查

logger.error(f"err: {e}")

```



> 补充：不要在同一个异常链里重复打异常堆栈（上层捕获又打一次，造成重复堆栈），底层抛出、上层统一记录一次即可。



## 6 日志内容安全规范（红线）



禁止打印：

- 明文密码、token、密钥、签名、私钥

- 身份证、手机号、银行卡等敏感隐私数据

- 完整大报文、大对象（DEBUG 阶段如需打印，做脱敏、截断）



敏感字段统一在日志格式化层做脱敏处理，而不是靠业务代码手动控制。



## 7 日志输出与 Handler 约定



1. 容器化部署（K8s / 云服务）：**优先输出 stdout，不写本地文件**，由采集器采集 stdout

2. 物理机/常驻脚本：使用轮转文件 `TimedRotatingFileHandler` / `RotatingFileHandler`，必须配置最大文件数量，防止磁盘打满

3. 禁止：无限追加日志文件、多 handler 重复输出同一条日志

4. 格式化器：线上统一 JSON formatter；开发环境使用人类可读的文本格式



## 8 propagate 传播约定



- 默认 `propagate=True`，日志向上传递到父 logger，一般不修改

- 只有明确需要隔离日志、单独输出、避免重复打印时，才设置 `propagate=False`，修改必须在组内对齐，备注原因

- 禁止随意关闭 propagate，容易出现日志丢失



## 9 禁止清单（日志红线）



1. 业务代码遗留 `print()` 用于正式流程观测（print 不属于日志体系，无法分级、结构化、采集）；调试 print 上线前必须删除

2. 大量循环内无差别打 DEBUG 日志（造成日志风暴、成本暴涨）

3. 用日志做业务消息投递、业务状态判断；日志仅用于观测，不做业务依赖

4. 随意新增全局 handler、修改 root logger 配置

5. 堆栈信息截断、人为吃掉异常不记录



## 10 配套示例



### 模块示例（service/user_service.py）

```python

import logging



logger = logging.getLogger(__name__)



def login_user(user_id: int, trace_id: str) -> bool:

 logger.info(

 "user_login_start",

 extra={"trace_id": trace_id, "user_id": user_id}

 )

 try:

 # 业务逻辑

 return True

 except Exception:

 logger.exception("user_login failed")

 return False

```



### 入口配置示例 main.py（dictConfig 极简模板）

```python

import logging

from logging.config import dictConfig



LOG_CONFIG = {

 "version": 1,

 "disable_existing_loggers": False,

 "formatters": {

 "console": {

 "format": "%(asctime)s %(name)s %(levelname)s %(message)s"

 }

 },

 "handlers": {

 "stdout": {

 "class": "logging.StreamHandler",

 "formatter": "console",

 "stream": "ext://sys.stdout"

 }

 },

 "root": {

 "level": "INFO",

 "handlers": ["stdout"]

 }

}



dictConfig(LOG_CONFIG)

logger = logging.getLogger(__name__)

logger.info("service started")

```



## 11 附则

1. 本规范为项目强制规范，CR 评审包含日志检查

2. 存量历史日志代码逐步改造，新增代码严格遵守

3. 如需新增日志字段、修改级别策略，需要组内统一对齐后更新文档

4. 本规范配合《Python 项目编程规范》一起执行