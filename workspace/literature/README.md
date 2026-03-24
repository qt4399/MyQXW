# literature workspace

- `state.yaml`: 文献整理的全局状态与默认参数。
- `index.yaml`: 全局去重后的论文索引。
- `categories/*.yaml`: 按类别整理后的中文论文条目。
- `learn/learn_tasks.yaml`: 真正控制哪些主题会被巡检，以及频率是多少。

现在文献整理由 `learn` 服务按显式配置调度；`workspace/literature` 只负责存储和执行。

使用方式：

1. 打开 `learn/learn_tasks.yaml`
2. 新增或修改 `runner: literature_poll` 的任务
3. 在 `options` 里填写 `category`、`topic`、频率等参数
4. 把任务的 `enabled` 改成 `true`
5. `learn` 会按频率触发文献检索，并把新论文整理进类别文件

常用任务参数：

- `search_queries_per_topic`: 每轮真正拿去搜的 query 数量
- `query_pool_size`: 缓存的短 query 池大小；模型不会每轮都重想
- `query_plan_refresh_seconds`: 多久重新规划一次 query 池
- `max_analyzed_papers_per_run`: 单轮最多进入模型深度分析的候选论文数
