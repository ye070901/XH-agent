# 事件总线（EventBus）设计文档

> 版本：v1.0 · 更新时间：2026-08-04
> 适用范围：学情诊断系统（agents / backend），进程内事件解耦。
> 读者对象：对接方架构人员。本文档给出统一消息格式、发布/订阅接口签名、选型依据、持久化日志规范，对接方可按第 1、2、4 章直接编写代码，无需额外沟通。

---

## 1. 统一消息格式

事件在总线上统一为一套固定结构，包含 **4 个固定字段**：`event_type`、`payload`、`timestamp`、`source`。任何事件不得在此 4 个字段之外增加顶层字段；业务数据一律放入 `payload`。

### 1.1 消息载体（内存对象）

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    """事件消息，固定 4 字段。frozen=True，发布后不可变。"""
    event_type: str   # 事件类型，见 1.3 命名规范
    payload: dict     # 业务数据，必须可被 json.dumps 序列化
    timestamp: str    # ISO8601 UTC 字符串，发布时刻
    source: str       # 发布者标识，见 1.2
```

### 1.2 字段定义与取值规范

| 字段 | 类型 | 含义 | 取值规范 | 是否可空 |
|------|------|------|----------|:--------:|
| `event_type` | `str` | 事件类型标识，订阅与路由的唯一依据 | 见 1.3 命名规范；必须匹配正则 `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$` | 否 |
| `payload` | `dict` | 业务数据，随事件传递 | 必须能被 `json.dumps(payload, ensure_ascii=False)` 序列化；学情诊断域事件 **应** 含 `learner_id`（str）作为第一条追踪字段 | 否（可为空字典 `{}`，不可为 `None`） |
| `timestamp` | `str` | 事件发生（被发布）时刻 | ISO8601 UTC，微秒精度，格式 `YYYY-MM-DDTHH:MM:SS.ffffffZ`，例：`2026-08-04T03:15:27.123456Z`；由总线在 `publish` 时自动生成，发布方**不得**自行传入 | 否 |
| `source` | `str` | 发布者标识，用于审计与问题定位 | 格式 `{模块}.{类或函数}`，例：`agents.diagnosis.DiagnosisAgent`；省略时自动取调用方模块名，**推荐显式传入** | 否 |

### 1.3 event_type 命名规范

- 全小写，多段用 `.` 分隔，每段为 `snake_case`。
- 结构：`{域}.{对象}.{动作}`，动作使用过去时（已完成）或进行时（进行中）明确状态。
- 预注册事件表（新增事件必须向本表登记，避免类型冲突）：

| 域 | 事件类型 | 触发场景 | payload 关键字段 |
|----|----------|----------|------------------|
| `agent` | `agent.diagnosis.started` | 诊断 Agent 开始执行 | `learner_id` |
| `agent` | `agent.diagnosis.completed` | 诊断完成并产出结果 | `learner_id`、`knowledge_map`、`skill_gaps` |
| `agent` | `agent.diagnosis.failed` | 诊断失败（解析失败 / 校验不通过） | `learner_id`、`error` |
| `llm` | `llm.request.sent` | 向 LLM 发起请求 | `model`、`prompt_tokens` |
| `system` | `system.bus.dropped` | 队列满被丢弃的事件 | 原事件 4 字段原样封入 |

> 禁止使用宽泛类型如 `event`、`message`；同一语义必须唯一类型。

### 1.4 消息示例

`agent.diagnosis.completed` 事件：

```json
{
  "event_type": "agent.diagnosis.completed",
  "payload": {
    "learner_id": "stu_2026_0001",
    "knowledge_map": [
      {"name": "LangGraph - 条件路由与动态分支", "mastery": 0.3}
    ],
    "skill_gaps": [
      {"skill": "图结构状态传递", "severity": "高"}
    ]
  },
  "timestamp": "2026-08-04T03:15:27.123456Z",
  "source": "agents.diagnosis.DiagnosisAgent"
}
```

### 1.5 校验规则（publish 时执行，fail-fast）

1. `event_type` 为空或不符合 1.3 正则 → 抛 `ValueError`。
2. `payload` 无法被 `json.dumps` 序列化（如含非可序列化对象）→ 抛 `ValueError`。
3. `source` 为空 → 自动回退为调用方模块名。
4. 以上校验失败时事件**不落盘、不入队**，直接抛异常给调用方。校验通过后，事件一经发布即不可变（`frozen=True`）。

---

## 2. 发布 / 订阅接口签名

总线以**模块级函数**形式对外暴露，内部委托给进程级单例。默认模型：**`publish` 入队即返回（异步派发），订阅者由后台调度线程消费**，实现生产-消费解耦。

### 2.1 发布接口

```python
def publish(event_type: str, payload: dict, *, source: str | None = None) -> None:
    """发布一条事件。

    Args:
        event_type: 事件类型，见 1.3 命名规范。
        payload:    业务数据字典，必须可 JSON 序列化。
        source:     发布者标识，省略时自动取调用方模块名。

    Returns:
        None。发布即入队返回，不等待订阅者执行完毕。

    Raises:
        ValueError: event_type 或 payload 不符合 1.5 校验规则。

    行为说明:
        - 入队成功后立即同步落盘 status=published 日志（见第 4 章）。
        - 入队超时（队列满）时不阻塞业务，事件以 status=dropped 落盘后返回。
        - 本函数只对参数校验抛异常；队列、日志、派发环节的异常绝不向调用方抛出。
    """
```

### 2.2 订阅接口

```python
def subscribe(event_type: str, handler: Callable[[Event], None]) -> Subscription:
    """订阅指定事件类型。

    Args:
        event_type: 要订阅的事件类型；传入 "*" 表示订阅所有事件（通配订阅）。
        handler:    回调函数，签名固定为 def handler(event: Event) -> None。

    Returns:
        Subscription: 订阅句柄，用于取消订阅。

    行为说明:
        - 同一 (event_type, handler) 重复订阅会被忽略（幂等注册）。
        - 订阅注册是线程安全的；订阅在注册时即可生效，此后发布的事件才会命中。
    """


def unsubscribe(subscription: Subscription) -> None:
    """取消订阅。对已取消/重复取消的句柄调用是安全的（幂等）。"""
```

### 2.3 订阅者回调签名

```python
def handler(event: Event) -> None:
    """订阅者回调。事件派发到订阅者时被调度线程调用。

    约束:
        - 必须同步返回 None；不返回值将被忽略。
        - 必须快速返回，禁止在回调内做阻塞式长任务或死循环；
          若需耗时处理，应自行投递到独立线程/进程。
        - 回调抛出的异常会被总线捕获并落盘 status=failed 日志，
          不影响该事件分发给其他订阅者，也不影响发布者。
    """
```

### 2.4 返回类型与生命周期

```python
class Subscription:
    """订阅句柄。"""
    id: str            # UUID4，唯一标识
    event_type: str    # 订阅的类型，或 "*"
    handler: Callable[[Event], None]

    def cancel(self) -> None:
        """等价于 unsubscribe(self)。"""


def shutdown(*, force: bool = False) -> None:
    """优雅关闭总线。

    - force=False（默认）: 停止接收新发布，后台线程将队列中剩余事件全部
      派发完成后退出。
    - force=True: 立即停止，剩余未消费事件全部以 status=dropped 落盘。
    """
```

### 2.5 线程模型与队列语义

- 全局维护一个 `queue.Queue(maxsize=1024)`，作为唯一消息通道。
- 一个**后台 daemon 调度线程**（首次 `subscribe` 时惰性启动）循环执行 `queue.get(timeout=0.5)`；每次 `TimeoutError` 时检查停止标志，决定是否继续。
- 派发流程（每取出一条事件）：
  1. 取出事件 `event`。
  2. 找到该事件 `event_type` 的订阅者列表，追加通配 `"*"` 订阅者（去重）。
  3. 依序调用每个订阅者回调；单个回调抛异常 → 捕获并落 `failed` 日志，继续分发下一个。
  4. 全部订阅者执行完毕（且有订阅者命中）→ 落 `dispatched` 日志。
  5. 无订阅者命中 → 不额外记录（`published` 日志已足够审计）。
- 所有队列操作（`put` / `get`）由 `queue.Queue` 保证线程安全，总线内部另用一把锁保护订阅注册表。

### 2.6 对接示例（结合现有 DiagnosisAgent）

```python
from event_bus import publish, subscribe


# ① 订阅：诊断完成后触发下游处理
def on_diagnosis_completed(event: Event) -> None:
    learner_id = event.payload.get("learner_id")
    print(f"收到诊断完成事件: {learner_id}")


sub = subscribe("agent.diagnosis.completed", on_diagnosis_completed)

# ② 发布：在 DiagnosisAgent.run 产出结果后调用
def run(self, state: dict) -> dict:
    ...  # 原有诊断逻辑，产出 state["diagnosis_result"]
    publish(
        "agent.diagnosis.completed",
        payload={
            "learner_id": state.get("learner_id", ""),
            "knowledge_map": state["diagnosis_result"].get("knowledge_map", []),
        },
        source="agents.diagnosis.DiagnosisAgent",
    )
    return state

# ③ 不再需要时取消订阅
sub.cancel()   # 或 unsubscribe(sub)
```

---

## 3. 选型说明：内置 `queue.Queue`，不接入 Redis

### 3.1 决策结论

**采用 Python 标准库 `queue.Queue` 作为进程内消息队列，明确不接入 Redis，也不引入任何外部消息中间件。**

### 3.2 选型理由

| 维度 | 内置 `queue.Queue` | Redis（Pub/Sub / List） |
|------|--------------------|-------------------------|
| 部署依赖 | 零依赖，随进程启动 | 需额外部署/维护 Redis 服务，配置连接、认证、监控 |
| 开发与测试 | 本地/CI 零配置即可运行 | 测试环境需启动实例或 mock，增加 CI 复杂度 |
| 延迟 | 进程内内存队列，微秒级 | 每次含网络 RTT + 序列化/反序列化，毫秒级 |
| 一致性 | 与业务进程同生命周期，天然同步 | 需考虑网络分区、连接中断、数据主从一致性 |
| 崩溃语义 | 进程崩溃即丢内存数据（由第 4 章持久化日志兜底） | 未持久化订阅缓存同样丢失，无法单靠 Redis 保证 |
| 适用规模 | 单进程、低频业务事件（学情诊断）完全够用 | 面向跨进程/跨主机、高吞吐场景 |

针对本项目（`BaseAgent.run(state)` 同步链式调用、低频事件），以上差距均不构成瓶颈，而 `queue.Queue` 的零运维、零延迟、零故障面优势直接成立。

### 3.3 明确不接入 Redis 的三条硬理由

1. **无跨进程需求**：当前系统为单进程架构，生产者与消费者同进程，不存在进程间共享队列的场景；引入 Redis 是架构上不必要的复杂度。
2. **避免外部依赖风险**：Redis 增加部署、认证、网络故障、版本维护等故障面；对学情诊断这种核心业务稳定性要求高的场景，减少外部依赖即减少故障点。
3. **能力超出需求**：Redis 的 TTL、消息确认/重试、订阅组等高级能力本项目均不需要；`queue.Queue` 的 `maxsize` 背压 + `put(timeout)` 足以覆盖需求。

### 3.4 能力边界与演进路线（诚实声明）

`queue.Queue` 的能力边界：**无法跨进程/跨主机共享队列**、**消息不原生持久化**（依赖第 4 章日志兜底）、**背压能力有限**（队列满即丢弃，靠日志留痕）。

为保留演进空间：事件总线对外只暴露第 2 章的 4 个函数，内部将队列实现抽象为 `Broker` 接口。**未来若出现多进程/水平扩展需求，只需新增一个 RedisBroker 实现并替换注入，业务调用方代码（publish/subscribe）零改动。** 该接口抽象已纳入本设计，但本期不实现。

---

## 4. 持久化日志格式规范

事件总线对每条事件落盘一份**审计日志**，保证事件可追溯、可重建、异常不丢失。

### 4.1 日志载体与文件布局

- **格式**：JSON Lines（JSONL），每行一个独立 JSON 对象，行尾 `\n`；UTF-8 编码，`ensure_ascii=False`（保留中文原文）。
- **默认路径**：`logs/eventbus.jsonl`（可通过配置项覆盖）。
- **写入方式**：追加写（append-only），日志行一经写入不可修改；`status` 流转通过追加新行表达，用 `log_id` 关联同一条事件的多行。

### 4.2 日志字段表

| 字段 | 类型 | 说明 |
|------|------|------|
| `log_id` | `str` | UUID4，事件唯一标识（一条事件的所有日志行共享同一 `log_id`） |
| `seq` | `int` | 单调递增序号（线程安全原子计数），用于排重/排序 |
| `event_type` | `str` | 事件类型，同消息字段 |
| `payload` | `object` | 业务数据，原样落盘 |
| `timestamp` | `str` | 事件发布时刻，ISO8601 UTC |
| `source` | `str` | 发布者标识 |
| `received_at` | `str` | 本行落盘时刻，ISO8601 UTC |
| `status` | `str` | 取值 `published` / `dispatched` / `failed` / `dropped`，见 4.3 |
| `handler` | `str` / `null` | 出问题的订阅者标识，仅 `failed` 行非空 |
| `error` | `str` / `null` | 异常摘要（含 traceback 首行），仅 `failed` 行非空 |
| `queue_depth` | `int` | 落盘时队列当前深度，诊断背压用 |

示例（同一条事件的三行）：

```json
{"log_id":"3f2c...","seq":42,"event_type":"agent.diagnosis.completed","payload":{"learner_id":"stu_1"},"timestamp":"2026-08-04T03:15:27.123456Z","source":"agents.diagnosis.DiagnosisAgent","received_at":"2026-08-04T03:15:27.123800Z","status":"published","handler":null,"error":null,"queue_depth":0}
{"log_id":"3f2c...","seq":43,"event_type":"agent.diagnosis.completed","payload":{"learner_id":"stu_1"},"timestamp":"2026-08-04T03:15:27.123456Z","source":"agents.diagnosis.DiagnosisAgent","received_at":"2026-08-04T03:15:27.128100Z","status":"dispatched","handler":null,"error":null,"queue_depth":0}
```

### 4.3 写入时机

| 时机 | `status` | 触发点 | 说明 |
|------|----------|--------|------|
| 事件**入队成功**后，`publish` 返回前 | `published` | 发布环节（同步落盘） | 审计起点，保证"发布即留痕" |
| 事件被全部订阅者**执行完毕**后 | `dispatched` | 调度线程派发完成 | 有订阅者命中时才写；无命中不写 |
| 某个订阅者回调**抛异常**时 | `failed` | 调度线程捕获异常 | 含 `handler` 与 `error`，记录后继续派发其余订阅者 |
| 事件**入队超时被丢弃**（队列满）时 | `dropped` | 发布环节（同步落盘） | 原事件 4 字段原样封入 payload 再落盘，保证业务数据不丢 |
| 优雅关闭 `shutdown(force=True)` 时 | `dropped` | 关闭流程 | 未消费的剩余事件逐一落盘 |

### 4.4 异常落盘规则

以下规则保证**事件在异常场景下仍尽可能留痕，且绝不向业务代码抛出总线异常**：

1. **订阅者回调异常**：捕获并落 `failed` 行，继续分发同一事件的其余订阅者；不影响发布者，不影响后续事件。
2. **队列满（`put` 超时）**：不阻塞业务 → 以 `dropped` 行落盘（payload 原样保留）→ 返回。可另发 `system.bus.dropped` 告警事件（可选）。
3. **日志文件写入失败（磁盘满 / 权限不足）**：按如下**兜底链路**依次尝试，任一步成功即止：
   - ① 主日志文件 `eventbus.jsonl`
   - ② 备用文件 `eventbus.jsonl.fallback`
   - ③ 内存环形缓冲（最多保留最近 200 条，供恢复后回补）+ `sys.stderr` 输出
   - ④ 以上全部失败 → 丢弃该行并递增丢弃计数（仅打印一次告警，避免刷屏）
4. **日志自身异常**（如 JSON 序列化失败）：不中断事件派发，异常按第 3 条兜底链路处理。
5. **进程崩溃**：内存队列中的未消费事件随之丢失，但事件在入队时已落 `published` 行 → 重启后**可依据日志重放**（见 4.5），实现"事件不静默丢失"。

### 4.5 日志轮转与重放

- **轮转**：按文件大小滚动（默认 50 MB，可配），滚动前把当前文件重命名为 `eventbus-{seq}.jsonl` 归档；归档文件同样保留，供事后审计。
- **重放**（可选能力，本期不实现）：
  - 提供 `replay(start_seq: int | None = None, *, from_dropped_only: bool = False) -> None` 接口说明。
  - 恢复流程：重启后扫描日志，取每条 `log_id` 的**最后一行** `status`；若最后为 `dropped` 或只有 `published` 而无 `dispatched`，则将该事件重新 `publish` 入队。
  - 重放必须**幂等**：订阅者需按 `payload.learner_id` 等业务键判重，避免重复处理。

---

## 附录 A：关键配置与常量

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `QUEUE_MAXSIZE` | `1024` | 队列容量，超出即背压丢弃 |
| `PUT_TIMEOUT` | `0.5`（秒） | 入队阻塞上限，超时按 `dropped` 处理 |
| `GET_TIMEOUT` | `0.5`（秒） | 调度线程取数心跳，用于检测停止标志 |
| `LOG_PATH` | `logs/eventbus.jsonl` | 审计日志路径 |
| `LOG_ROTATE_BYTES` | `50 * 1024 * 1024` | 日志滚动阈值 |
| `FALLBACK_BUFFER_SIZE` | `200` | 内存兜底缓冲条数上限 |

> 对接方只需实现第 2 章接口与第 1 章消息结构即可完成接入；第 3、4 章为架构决策与运行时约束，通常不需要对接方改动。
