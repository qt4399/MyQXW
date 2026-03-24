# v1.0
# 项目架构说明

## 项目介绍

这是一个面向长期陪伴与持续运行场景的本地 Agent 项目。它不只是一次性回答问题的聊天程序，而是一个带有**短期上下文**、**后台记忆整理**、**月度归档**、**主观中断**和**显式学习计划**的常驻智能体。

它的目标不是让 Agent 每次都从零开始，而是让它在长期运行中逐步形成稳定的记忆分层与行为边界：

- 普通对话时，短期记忆仍保存最近 20 轮，但默认只向模型注入最近 6 轮对话，再结合 `day.md` 和最近 30 天概括理解上下文。
- 溢出的旧对话不会直接交给 `heart`，而是由独立的 `sleep` 服务在后台慢慢整理。
- 每天凌晨 4:00 后，程序会自动把昨天的 `day.md` 归档进 `month.md`，形成最近 30 天可检索的记录。
- 外部学习任务不走神经元脉冲，而是由 `learn/learn_tasks.yaml` 显式控制开关与时间间隔。

整个项目遵循“**程序负责结构与边界，Agent 负责语义整理与轻量决策**”的思路：程序保证记忆文件、时间规则、归档流程和调度边界稳定可靠；Agent 负责理解内容、提炼主题、维护 day 记忆，并在少数时刻进行主观响应。

## 使用方式

### 1. 环境准备

推荐先进入项目目录：

```bash
cd MyQXW
```

然后安装依赖：

```bash
pip install -r requirements.txt
```

如果你需要启用额外能力，还需要补充这些环境项：

- `Playwright` 浏览器自动化：

  ```bash
  playwright install chromium
  ```

- `pdf2image` 依赖的系统工具（Ubuntu / Debian）：

  ```bash
  sudo apt-get install -y poppler-utils
  ```

接着检查并填写模型配置文件：

- `config.json`
- 需要确认其中的模型名称、`base_url` 和 `api_key` 可正常使用
- 其中当前代码实际会读取：
  - `gpt_model` / `gpt_base_url` / `gpt_api_key`
  - `heart_model` / `heart_base_url` / `heart_api_key`
  - `emotion_model` / `emotion_base_url` / `emotion_api_key`
  - `word_model` / `word_base_url` / `word_api_key`

如果你要接入 QQ / NapCat，还需要检查：

- `qq_api_reference/local_config.json`
- 需要确认其中的 WebSocket 地址和 token 可正常使用

### 2. 启动统一调度器

直接运行：

```bash
cd MyQXW
python main.py
```

启动后会发生这些事：

- 后台启动 `heart` / `sleep` / `learn` / `scheduler` 四个服务。
- 启动 OpenAI-compatible API：`http://127.0.0.1:8000/v1/chat/completions`
- 尝试启动 QQBridge（如果 NapCat 配置不可用，会打印失败信息）

注意：

- 当前 `main.py` 不提供本地终端聊天 REPL。
- 它更像一个服务进程，聊天入口主要是 OpenAI-compatible API 和 QQBridge。

### 3. 本地调试对话接口

仓库里带了一个简单的本地命令行客户端：

```bash
cd MyQXW
python demo/openai_request.py
```

这个脚本会通过 `transport/openai_api.py` 暴露的兼容接口发起对话，适合快速本地联调。

### 4. 查看后台日志

后台服务会分别把最近活动写到这些日志文件：

- `logs/heart_log.yaml`
- `logs/sleep_log.yaml`
- `logs/learn_log.yaml`

每个日志文件最多保留最近 100 条记录。

更细的字段说明见 `LOGS.md`。

如果你想在另一个终端实时观察，可以直接查看这个文件：

```bash
cd MyQXW
cat logs/heart_log.yaml
```

### 5. 可选：QQ / NapCat 接入

当前仓库没有单独的 REPL 调试入口；后台服务由 `main.py` 统一拉起。

如果你要通过 QQ 收发消息：

- 先确保 NapCat 正常运行
- 再检查 `qq_api_reference/local_config.json`
- 然后启动 `python main.py`

## 整体架构图

### 1. 组件视角

```text
┌──────────────┐
│     用户      │
└──────┬───────┘
       │ 输入消息
       v
┌────────────────────┐
│ transport / main   │
│ API / QQ / 统一启动 │
└─────────┬──────────┘
          │
          ├──────────────→ `language/chat_service.py`
          ├──────────────→ `congnition/heart_service.py`
          ├──────────────→ `sleep/sleep_service.py`
          ├──────────────→ `learn/learn_service.py`
          └──────────────→ `scheduler/scheduler_service.py`

┌────────────────────┐    ┌────────────────────┐    ┌────────────────────┐
│ init.py            │    │ memory_store.py    │    │ logs/*.yaml        │
│ 模型 / prompt / 工具 │    │ 共享记忆存储与锁    │    │ heart/sleep/learn  │
└─────────┬──────────┘    └─────────┬──────────┘    └────────────────────┘
          │                         │
          └──────────────┬──────────┘
                         v
              ┌────────────────────┐
              │ memory / workspace  │
              │ yaml + md + 文献库   │
              └────────────────────┘
```

### 2. 运行时数据流

```text
┌────────────────────┐
│ 用户发送消息        │
└─────────┬──────────┘
          │
          v
┌────────────────────┐
│ init.py 组装输入    │
│ - 规则文档          │
│ - 最近6轮对话       │
│ - day.md            │
│ - 最近30天概括      │
└─────────┬──────────┘
          │
          v
┌────────────────────┐
│ chat model 回复     │
└─────────┬──────────┘
          │
          v
┌────────────────────┐
│ append_dialogue_   │
│ round 写回对话      │
└─────────┬──────────┘
          │
          ├──────────────→ `communicate.yaml` 保留最近 20 轮
          │
          └──────────────→ 超出窗口部分进入 `temp_communicate.yaml`

┌────────────────────┐
│ scheduler 周期轮询  │
└─────────┬──────────┘
          │
          ├──────────────→ 归档检查：`archive_day_to_month()`
          ├──────────────→ 神经元评估：`temp_overflow_pressure`
          ├──────────────→ 神经元评估：`day_closure_pressure`
          └──────────────→ 神经元评估：`subjective_pulse`

┌────────────────────┐    ┌────────────────────┐
│ sleep 任务队列      │    │ heart 中断队列      │
└─────────┬──────────┘    └─────────┬──────────┘
          │                         │
          ├──────────────→ `temp_digest`
          ├──────────────→ `daily_summary`
          │                         └──────────────→ `interrupt`
          v
┌────────────────────┐
│ learn 固定周期任务  │
└─────────┬──────────┘
          │
          └──────────────→ `literature_poll`


备注：chat / heart / sleep / learn 会并行工作；共享的 memory 文件由 `memory_store.py` 串行保护，避免读写冲突。
```

### 3. 记忆层级视角

```text
┌────────────────────┐
│ 短期上下文层        │
│ communicate.yaml    │
│ 保存最近 20 轮对话    │
└─────────┬──────────┘
          │ 溢出
          v
┌────────────────────┐
│ 待整理缓冲层        │
│ temp_communicate    │
│ 等待 sleep 整理     │
└─────────┬──────────┘
          │ 神经元触发
          v
┌────────────────────┐
│ 当天记忆层          │
│ day.md              │
│ 概括 + 详细         │
└─────────┬──────────┘
          │ 次日凌晨 4:00 后归档
          v
┌────────────────────┐
│ 月归档层            │
│ month.md            │
│ 最近 30 天记录      │
│ 每天 = 概括 + 详细  │
└────────────────────┘
```

这个项目现在按“脑区服务”拆成了五层：`chat`、`heart`、`sleep`、`learn`、`scheduler`。

## 目录结构

- `main.py`：统一启动入口，启动 chat、heart、sleep、learn、scheduler、OpenAI API 和 QQBridge
- `language/chat_service.py`：聊天服务实现，负责 logic + emotion + 记忆回写
- `congnition/heart_service.py`：主观认知区服务，只接收和处理主观中断
- `sleep/sleep_service.py`：后台记忆整理服务，负责 temp 对话整理与每日概括
- `learn/learn_service.py`：外部学习服务，按显式配置定期执行文献/资料任务
- `scheduler/scheduler_service.py`：神经元调度器，负责内部脉冲与任务投递
- `init.py`：组装模型、系统提示、工具和输入上下文
- `memory/memory_store.py`：记忆读写、日/月归档和共享状态维护
- `memory/image_store.py`：图片引用存储与 `<image id=\"...\" />` 标签管理
- `transport/openai_api.py`：OpenAI-compatible Chat Completions 接口
- `transport/qq_bridge.py`：QQ / NapCat 消息桥接
- `skill/chat_base_skill.py` + `skill/chat_extra_skill.py`：前台对话区工具
- `skill/heart_base_skill.py` + `skill/heart_extra_skill.py`：主观认知区工具
- `skill/sleep_base_skill.py` + `skill/sleep_extra_skill.py`：睡眠整理区工具
- `demo/openai_request.py`：本地调试 OpenAI-compatible API 的简单客户端
- `workspace/literature/`：文献巡检的状态、索引与分类存储
- `memory/md/`：自然语言记忆与规则文档
- `memory/yaml/`：结构化状态与短期对话数据
- `logs/heart_log.yaml` / `logs/sleep_log.yaml` / `logs/learn_log.yaml`：后台服务日志

## 整体工作流

### 1. 普通对话

用户消息通常通过 `transport/openai_api.py` 或 `transport/qq_bridge.py` 进入，然后交给 `language/chat_service.py`，再走 `init.py` 里的普通对话链路：

1. 注入基础人格与规则文档
2. 从 `communicate.yaml` 中截取最近 6 轮对话上下文
3. 注入 `day.md`
4. 注入最近 30 天概括
5. 调用模型生成回复
6. 把 logic 草稿交给 emotion 层做语气润色
7. 把这一轮用户/助手对话写入 `communicate.yaml`
8. 如果超过 20 轮，最旧对话会溢出到 `temp_communicate.yaml`

### 2. 主观中断

`congnition/heart_service.py` 不再做后台整理调度，而是一个中断处理器。它接收来自 `scheduler` 的主观脉冲，再由 heart 区模型决定是否做一次轻量响应或状态更新。

### 3. 睡眠整理

`sleep/sleep_service.py` 负责后台无意识整理，主要处理：

- `temp_communicate.yaml` 的溢出对话整理
- `day.md` 的概括更新
- 日记忆向月归档前的收束

这些任务不再由 `heart` 主动轮询，而是由 `scheduler` 的 homeostatic neurons 触发。

### 4. 外部学习

`learn/learn_service.py` 负责文献巡检、资料阅读和后续资料库更新。它不走神经元脉冲，而是由你显式配置开关和固定间隔，例如 `learn/learn_tasks.yaml` 里的 `literature_poll` 任务。

### 5. 神经元调度

`scheduler/scheduler_service.py` 只负责内部脉冲，不直接做语义整理。当前默认神经元包括：

- `temp_overflow_pressure`：推动 `sleep.temp_digest`
- `day_closure_pressure`：推动 `sleep.daily_summary`
- `subjective_pulse`：推动 `heart.interrupt`

## 记忆分层

### 短期层

- `memory/yaml/communicate.yaml`
  - 保存最近 20 轮对话
  - 普通聊天时默认只截取最近 6 轮注入模型

- `memory/yaml/temp_communicate.yaml`
  - 保存从 `communicate.yaml` 溢出的旧对话
  - 等待 `sleep` 服务进行主题整理

### 当天层

- `memory/md/day.md`
  - 保存当前记忆日的重要内容
  - 结构分为：
    - `## 概括`
    - `## 详细`
  - 由 `sleep` 服务逐步整理

### 月归档层

- `memory/md/month.md`
  - 保存最近 30 天的按天归档
  - 每一天都包含：
    - `### 概括`
    - `### 详细`
  - 只保留最近 30 天窗口

### 状态层

- `memory/yaml/state.yaml`
  - 保存运行状态与时间戳
  - 包括：
    - 当前记忆日
    - 最近一次用户消息时间
    - 最近一次助手消息时间
  - 最近一次主观中断处理时间
  - 最近一次日归档时间
  - 最近一次临时对话整理完成时间
  - `play` 的启用状态、激活状态和触发时间

  说明：运行中的聊天 / heart / sleep / learn / scheduler 服务不直接把内部线程状态落到 `state.yaml`，这里只保存跨服务需要共享的记忆状态与时间戳。

## 记忆日规则

这个项目的“记忆日”不是按 00:00 切换，而是按**凌晨 4:00**切换。

也就是说：

- 凌晨 4:00 之前，仍然算前一个记忆日
- 凌晨 4:00 之后，旧的 `day.md` 会归档进 `month.md`
- 然后开始一个新的 `day.md`

这样做是为了兼容夜间仍在持续的对话和活动。

## Prompt 注入策略

### 普通对话默认注入

- 基础人格与规则文档
- 默认注入最近 6 轮对话（底层仍保存最近 20 轮）
- `day.md`
- 最近 30 天概括

### 主观中断默认注入

- 基础人格与规则文档
- `day.md`
- 最近 30 天概括
- `INTERRUPTS.md`
- 本次中断包（中文）

### 睡眠整理默认注入

- 基础人格与规则文档
- `day.md`
- 最近 30 天概括
- `SLEEP.md`
- 本次睡眠任务描述（中文）

## Tool 设计

当前实现把工具按“脑区”拆成三组：

- 对话区 `skill/chat_base_skill.py` + `skill/chat_extra_skill.py`
  - `run_command`
  - `read_month_day`
  - `obtain_photo`
  - `inspect_image`
  - `inspect_images`
  - `send_picture_qq`

- 主观认知区 `skill/heart_base_skill.py` + `skill/heart_extra_skill.py`
  - `run_command`
  - `read_state`
  - `update_state`
  - `read_month_day`

- 睡眠整理区 `skill/sleep_base_skill.py` + `skill/sleep_extra_skill.py`
  - `run_command`
  - `read_state`
  - `update_state`
  - `read_temp_communicate`
  - `delete_temp_rounds`
  - `update_day_summary`
  - `append_day_md`
  - `read_month_day`

其中：

- 最近 30 天概括是**默认注入**的，不需要额外工具读取
- `day.md` / `temp_communicate.yaml` 的维护能力只开放给睡眠整理区
- `state.yaml` 的轻量更新能力开放给 heart 与 sleep
- 对话区默认不直接操作日记忆整理流程
- 浏览器类工具默认走 Chrome 引擎，并按会话复用独立浏览器 session

## 当前实现边界

当前架构里：

- 对话到 `communicate.yaml` / `temp_communicate.yaml` 的转移是程序自动做的
- `day.md` 的整理主要由 sleep 区模型在后台任务中完成
- `month.md` 的归档由程序在凌晨 4:00 后自动完成，`scheduler` 会持续维护这个边界
- `month.md` 的“某一天详细内容检索”通过工具完成
- learn 的文献巡检由显式配置控制，不走神经元脉冲
- scheduler 只负责内部脉冲，不直接做语义整理
- chat / heart / sleep / learn 会并行工作，但共享存储由 `memory_store.py` 统一加锁保护

因此这是一个：

- 程序负责结构与边界
- Agent 负责语义整理与主观响应

的混合架构。
