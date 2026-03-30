# ChatService 接口文档

## 统一入口

### `dispatch(session_id, content, image_path="", should_interrupt=None) -> Iterator[dict]`

Transport 层统一调用此方法，内部转发至 `stream_reply_events()`。

---

## 流式事件接口

### `stream_reply_events(...) -> Iterator[dict]`

按顺序 yield 以下结构化事件：

#### 阶段一：Logic

| 事件类型 | 结构 | 说明 |
|---|---|---|
| `tool_call` | `{"type": "tool_call", ...}` | 工具调用（具体字段由 logic_service 决定） |
| `tool_result` | `{"type": "tool_result", ...}` | 工具返回结果 |
| `text` | `{"type": "text", "content": str}` | logic 阶段流式文字 chunk |
| `interrupted` | `{"type": "interrupted"}` | 被中断，后续不再 yield |

#### 阶段二：Emotion 润色

| 事件类型 | 结构 | 说明 |
|---|---|---|
| `emotion_start` | `{"type": "emotion_start"}` | 情感润色开始 |
| `text` | `{"type": "text", "content": str, "stage": "emotion"}` | 润色阶段流式文字 chunk |
| `interrupted` | `{"type": "interrupted"}` | 被中断，后续不再 yield |

#### 结束

| 事件类型 | 结构 | 说明 |
|---|---|---|
| `done` | `{"type": "done", "content": str}` | 最终完整可见回复（已去除内部标记） |

> `done.content` 为经过 `_sanitize_visible_reply()` 处理后的最终文本，去除了图片标签等内部标记，可直接展示给用户。

---

## 其他接口

| 方法 | 返回类型 | 说明 |
|---|---|---|
| `chat(user_prompt, session_id, ...)` | `str` | 阻塞调用，返回最终回复文本 |
| `chat_interruptible(user_prompt, session_id, ...)` | `tuple[str, bool]` | `(最终回复, 是否被中断)` |
| `chat_stream(user_prompt, session_id, ...)` | `Iterator[str]` | 流式纯文本 chunk，无结构化事件 |

---

## 典型事件序列示例

```
{"type": "tool_call", ...}
{"type": "tool_result", ...}
{"type": "text", "content": "正在思考"}
{"type": "text", "content": "……"}
{"type": "emotion_start"}
{"type": "text", "content": "好的，", "stage": "emotion"}
{"type": "text", "content": "我来帮你！", "stage": "emotion"}
{"type": "done", "content": "好的，我来帮你！"}
```
