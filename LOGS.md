# LOGS.md

项目当前的运行日志分成两类：后台服务日志和工具产物。

## 后台服务日志

这些日志都写在 `logs/` 目录下，默认最多保留最近 100 条：

- `logs/heart_log.yaml`
  - 来源：`congnition/heart_service.py`
  - 作用：记录主观中断处理结果
  - 字段：
    - `time`：触发时间
    - `runner`：中断类型，当前默认是 `interrupt`
    - `source`：脉冲来源，例如 `subjective_pulse`
    - `status`：`ok` 或 `error`
    - `response`：模型返回内容
    - `error`：异常信息

- `logs/sleep_log.yaml`
  - 来源：`sleep/sleep_service.py`
  - 作用：记录后台记忆整理任务
  - 字段：
    - `time`：触发时间
    - `runner`：任务类型，例如 `temp_digest`、`daily_summary`
    - `source`：脉冲来源，例如 `temp_overflow_pressure`
    - `status`：`ok` 或 `error`
    - `response`：模型返回内容
    - `error`：异常信息

- `logs/learn_log.yaml`
  - 来源：`learn/learn_service.py`
  - 作用：记录显式配置驱动的学习任务
  - 字段：
    - `time`：执行时间
    - `task_id`：任务 ID
    - `task_name`：任务名称
    - `status`：`ok` 或 `error`
    - `response`：任务摘要
    - `error`：异常信息

## 工具产物

这些不是结构化日志，而是工具运行后留下的文件：

- `logs/captures/`
  - 拍照工具输出

- `logs/screenshots/`
  - 屏幕截图工具输出

- `logs/browser_captures/`
  - 浏览器抓图输出

- `logs/browser_profiles/`
  - 浏览器自动化留下的用户数据目录
  - 这类目录里通常会包含 `Default`、`Local State`、`DevToolsActivePort`、缓存和数据库文件
  - 它们更像运行时 profile / session 数据，而不是日志文本
  - 从当前仓库代码搜索结果看，没有发现新的直接写入引用；更可能是历史浏览器调试或自动化运行遗留

## 记忆关联

- `memory/yaml/images.yaml` 会记录图片引用
- 这些引用可能指向：
  - `logs/captures/`
  - `logs/screenshots/`
  - `logs/browser_captures/`
- 所以这些图片文件虽然不属于结构化日志，但可能仍被记忆系统引用，不适合随手清空

## 历史说明

- 旧版架构曾使用 `logs/heartbeat_log.yaml` 记录 heartbeat / 心智整理任务。
- 当前仓库已经切换到 `heart + sleep + learn + scheduler` 架构，这个旧日志不再使用。
- 如果未来再看到名为 `heartbeat_log.yaml` 的文件，应该把它视为历史遗留，而不是当前主日志。
