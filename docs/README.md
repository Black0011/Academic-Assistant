# Academic Agent Framework — Documentation

## English

| Doc                                                | Audience                  | What you get                                            |
|----------------------------------------------------|---------------------------|---------------------------------------------------------|
| [`architecture.md`](architecture.md)               | new contributor / SRE     | runtime topology, subsystems, data flow, deploy modes   |
| [`runtime-internals.md`](runtime-internals.md)     | framework maintainer      | how the moving parts cooperate at runtime — context management, conversation isolation, prompt assembly, provider stack, memory access |
| [`api-reference.md`](api-reference.md)             | API consumers             | every HTTP endpoint with request/response shapes        |
| [`writing-your-own-skill.md`](writing-your-own-skill.md) | skill author        | L1 capability + L2 rule + L3 heuristic walk-through     |
| [`writing-your-own-llm-provider.md`](writing-your-own-llm-provider.md) | LLM integrator | implement and register a new `LLMProvider`             |
| [`laptop-mode.md`](laptop-mode.md)                 | personal user             | sqlite + in-memory queue preset for one-laptop install   |

## 中文

| 文档 | 受众 | 内容 |
|------|------|------|
| [`runtime-internals.zh.md`](runtime-internals.zh.md) | 框架维护者 | 运行时各部件如何协作 —— 上下文管理、对话隔离、提示词拼接、Provider 装饰器栈、记忆访问、运行时配置覆盖、前端中英双语（与英文版章节编号一一对应） |

The `PLAN.md` at the repo root tracks delivery milestones (M0–M6, P0–P6);
the deployment guide lives next to its compose file at
[`deploy/README.md`](../deploy/README.md). Subsystem-specific maps are in
`AGENTS.md` files (`backend/AGENTS.md`, `skills/AGENTS.md`,
`rules/AGENTS.md`, `backend/workflows/AGENTS.md`).
