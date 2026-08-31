import { AnimatePresence, motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "framer-motion";
import { ArrowDown, ArrowRight, ArrowRightCircle, ArrowUp, BrainCircuit, Download, Maximize2, Menu, Minimize2, Search, ShieldCheck, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from "react";
import { assessLearningGoal, askStudyQuestion, createDemoQuiz, refineLearningGoal, resolveQuizAnswerKey, submitQuiz, type ClarificationQuestion, type LearnerQuestionResponse, type Quiz, type QuizSubmissionResult } from "./learning-session";
import { getApiBase, initialWorkflowEvents, mergeWorkflowEvent, simulateWorkflow, subscribeWorkflow, workflowStages, type WorkflowEvent } from "./workflow-stream";

type Variant = "a" | "b";

const navigation = ["系统概览", "学习诊断", "知识生成", "审核修正", "学习工作台"];
const workflowSteps = ["目标澄清", "知识检索与生成", "审核修正与答疑"];
const ease = [0.22, 1, 0.36, 1] as const;
type Panel = "overview" | "diagnosis" | "generation" | "audit" | "workspace";
type QualityGate = "evidence" | "difficulty" | "expression";
type WorkspaceDialog = { kind: "workflow"; index: number } | { kind: "quality"; id: QualityGate };

const panelIds: Panel[] = ["overview", "diagnosis", "generation", "audit", "workspace"];
const panelDetails: Record<Panel, { eyebrow: string; title: string; description: string; metric: string }> = {
  overview: { eyebrow: "系统概览", title: "从学习数据到可信资源", description: "学习画像、知识检索与审核修正由同一条可追踪的工作流连接。", metric: "4 个 Agent 协同" },
  diagnosis: { eyebrow: "学习诊断", title: "先理解学习者，再开始生成", description: "诊断 Agent 汇总学习进度、能力缺口与目标，建立可解释的学习画像。", metric: "画像维度持续更新" },
  generation: { eyebrow: "知识生成", title: "让内容有来源，也有边界", description: "生成 Agent 基于 RAG 检索结果组织题目、讲解和学习任务。", metric: "32 篇知识文档可用" },
  audit: { eyebrow: "审核修正", title: "每份资源都经过质量闸门", description: "审核与保真 Agent 检查事实依据、难度匹配和表达质量，再完成修正。", metric: "3 道质量闸门" },
  workspace: { eyebrow: "学习工作台", title: "把协作过程留在同一个界面", description: "在工作台中查看任务进度、生成记录与每个 Agent 的可追溯输出。", metric: "过程全程可追溯" },
};

Object.assign(panelDetails, {
  overview: {
    eyebrow: "系统能力",
    title: "从明确目标到可验证学习",
    description: "追问澄清目标、检索可信知识、生成可学习资源，并支持答题反馈和学习过程中的针对性补充。",
    metric: "目标到反馈闭环",
  },
  diagnosis: {
    eyebrow: "学习诊断",
    title: "先澄清目标，再建立画像",
    description: "当目标过于宽泛时，系统通过追问补全学习范围、预期成果和时间边界，形成可执行的学习方向。",
    metric: "目标与能力双维画像",
  },
  generation: {
    eyebrow: "知识生成",
    title: "检索支撑的多类型资源",
    description: "生成 Agent 结合知识库检索，输出讲义、实操指南与可提交作答的测试题。",
    metric: "讲义、指南、测试题",
  },
  audit: {
    eyebrow: "审核修正",
    title: "审核、修正与权威性提示",
    description: "审核 Agent 检查事实依据、难度和表达；修正流程保留可追溯问题，并对无权威参考内容明确提示。",
    metric: "审核结果可查看",
  },
  workspace: {
    eyebrow: "学习工作台",
    title: "实时看见 Agent 如何工作",
    description: "任务执行时展示诊断、检索、生成、审核与修正的状态；完成后继续答题与获得针对性补充。",
    metric: "实时状态与学习反馈",
  },
});

const resourceOptions = [
  { id: "lecture", label: "讲义" },
  { id: "guide", label: "实操指南" },
  { id: "quiz", label: "测试题" },
  { id: "project", label: "项目实战" },
  { id: "pitfall_guide", label: "避坑指南" },
];

type GeneratedResource = {
  resource_id?: string;
  resource_type: string;
  title: string;
  content?: string;
  difficulty_level?: string;
  estimated_duration_minutes?: number;
  key_takeaways?: string[];
  quiz?: Quiz;
  quiz_validation_status?: "needs_review";
  quiz_validation_error?: string;
  supplements?: Array<{ title: string; content: string }>;
  risk_level?: "theory" | "low_risk" | "high_risk";
  safety_warnings?: string[];
  robot_metadata?: { brand?: string; controller_version?: string; applicable_model?: string };
  instruction_links?: Array<{ brand?: string; name?: string; doc_id?: string; doc_title?: string }>;
  alarm_links?: Array<{ brand?: string; code?: string; doc_id?: string; doc_title?: string; fault_name?: string }>;
  citations?: Array<{ doc_id?: string; doc_title?: string; chunk_index?: number; original_text?: string; relevance_score?: number }>;
};

function getResourceSupplements(resource: GeneratedResource) {
  if (resource.supplements?.length) return resource.supplements;
  // Older in-memory resources use this existing marker instead of the field.
  if (!resource.key_takeaways?.includes("已根据你的学习疑问补充说明")) return [];
  const legacyMatch = (resource.content ?? "").match(/\n\n##\s+([^\n]+)\n\n([\s\S]+)$/);
  return legacyMatch ? [{ title: legacyMatch[1].trim(), content: legacyMatch[2].trim() }] : [];
}

function getExportBaseContent(resource: GeneratedResource, supplements: Array<{ title: string; content: string }>) {
  let content = resource.content ?? "";
  for (const supplement of [...supplements].reverse()) {
    const marker = `\n\n## ${supplement.title}\n\n${supplement.content}`;
    if (content.endsWith(marker)) content = content.slice(0, -marker.length);
  }
  return content;
}

type SkillGap = {
  topic?: string;
  current_level?: number;
  target_level?: number;
  priority?: string;
  reason?: string;
};

type KnowledgePoint = {
  id?: string;
  topic?: string;
  level?: string;
  aliases?: string[];
  source_documents?: string[];
};

type KnowledgeDomain = {
  id?: string;
  name?: string;
  knowledge_points?: KnowledgePoint[];
};

type CoreMap = {
  meta?: Record<string, unknown>;
  domains?: KnowledgeDomain[];
};

type KnowledgePointView = KnowledgePoint & {
  is_weak?: boolean;
  mastery?: number;
  target?: number;
  priority?: string;
  reason?: string;
};

type GenerationErrorItem = {
  resource_type?: string;
  error?: string;
  detail?: string | string[];
  stage?: string;
  timestamp?: string;
  raw_error?: string;
};

type GenerationResult = {
  task_id?: string;
  status?: string;
  diagnosis?: { summary?: string; learning_style?: string; recommended_difficulty?: string; skill_gaps?: SkillGap[] };
  resources?: GeneratedResource[];
  audit?: Array<{ resource_index?: number; resource_type?: string; verdict?: string; issues?: Array<{ detail?: string }> }>;
  agent_log?: Array<{ agent?: string; status?: string }>;
  generation_errors?: GenerationErrorItem[];
  mode?: "demo" | "api";
};

type QuizAttempt = {
  answers: Record<string, string>;
  submitted: boolean;
  quizResult: QuizSubmissionResult | null;
  quizError: string | null;
  resolvedQuiz: Quiz | null;
};

const createQuizAttempt = (): QuizAttempt => ({
  answers: {},
  submitted: false,
  quizResult: null,
  quizError: null,
  resolvedQuiz: null,
});

const quizAttemptKey = (resource: GeneratedResource) => resource.resource_id
  ?? `${resource.resource_type}:${resource.title}`;

const safetyAckStorageKey = (key: string) => `xh-safety-ack:${key}`;

const hasAcknowledgedSafety = (key: string) => {
  try {
    return localStorage.getItem(safetyAckStorageKey(key)) === "1";
  } catch {
    return false;
  }
};

const acknowledgeSafety = (key: string) => {
  try {
    localStorage.setItem(safetyAckStorageKey(key), "1");
  } catch {
    // 私密窗口 / 浏览器禁用站点数据时写入会抛异常；仅内存态兜底，不阻断学习
  }
};

const isQuizResourceType = (type?: string) => type === "quiz" || /^quiz_round_\d+$/.test(type ?? "");

const isHandsOnResourceType = (type?: string) => type === "guide" || type === "project";

const resourceLabel = (type: string) => {
  const round = type.match(/^quiz_round_(\d+)$/)?.[1];
  if (round) return `\u7b2c ${round} \u8f6e\u6d4b\u8bd5`;
  return resourceOptions.find((option) => option.id === type)?.label ?? type;
};

const generationErrorIsSoft = (item: GenerationErrorItem) =>
  item.error === "invalid_quiz_contract" || item.error === "structure_sections_missing";

const generationErrorDetail = (item: GenerationErrorItem) => {
  const detail = item.detail;
  if (Array.isArray(detail)) {
    const joined = detail.map((part) => decodeEscapedText(part)).filter(Boolean).join("\uff1b");
    if (joined) return joined;
  } else if (typeof detail === "string" && detail.trim()) {
    return decodeEscapedText(detail);
  }
  return decodeEscapedText(item.error || "\u672a\u77e5\u539f\u56e0");
};

const generationErrorTitle = (item: GenerationErrorItem) => {
  if (item.error === "invalid_quiz_contract") return "\u6d4b\u8bd5\u9898\u5df2\u751f\u6210\uff0c\u4f46\u6682\u4e0d\u7b26\u5408\u81ea\u52a8\u8bc4\u5206\u6761\u4ef6";
  if (item.error === "structure_sections_missing") return resourceLabel(item.resource_type || "\u8d44\u6e90") + "\u5df2\u751f\u6210\uff0c\u4f46\u7f3a\u5c11\u5b89\u5168\u76f8\u5173\u7ae0\u8282";
  return resourceLabel(item.resource_type || "\u8d44\u6e90") + "\u672a\u751f\u6210";
};

const stageLabel = (stage?: string) => {
  switch (stage) {
    case "llm_generate": return "LLM \u751f\u6210";
    case "topic_check": return "\u4e3b\u9898\u6821\u9a8c";
    case "structure_check": return "\u7ed3\u6784\u6821\u9a8c";
    case "quiz_check": return "\u6d4b\u8bd5\u9898\u6821\u9a8c";
    case "generation": return "\u751f\u6210\u9636\u6bb5";
    default: return stage || "\u672a\u77e5\u9636\u6bb5";
  }
};

const formatErrorTime = (timestamp?: string) => {
  if (!timestamp) return "\u672a\u77e5";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return date.toLocaleString();
};

function GenerationFailures({ errors, onRegenerate }: { errors: GenerationErrorItem[]; onRegenerate: () => void }) {
  const [acknowledged, setAcknowledged] = useState<Record<number, boolean>>({});
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  if (!errors.length) return null;
  const activeCount = errors.filter((_item, index) => !acknowledged[index]).length;

  return (
    <div className="mt-4 grid gap-3">
      {activeCount > 0 ? (
        <div className="flex items-start gap-3 rounded-xl border border-red-400/40 bg-red-400/15 px-4 py-3 text-sm leading-6 text-red-50">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" />
          <p className="min-w-0 flex-1">
            <span className="font-semibold">{activeCount}{" \u4e2a\u8d44\u6e90\u751f\u6210\u5931\u8d25"}</span>
            <span className="ml-1 text-red-50/75">{"\uff0c\u672a\u751f\u6210\u7684\u8d44\u6e90\u4e0d\u4f1a\u51fa\u73b0\u5728\u4e0a\u65b9\u6807\u7b7e\uff0c\u5df2\u751f\u6210\u8d44\u6e90\u4e0d\u53d7\u5f71\u54cd\u3002\u70b9\u300c\u67e5\u770b\u8be6\u60c5\u300d\u53ef\u6eaf\u6e90\u3002"}</span>
          </p>
        </div>
      ) : (
        <p className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/60">{"\u5931\u8d25\u63d0\u793a\u5df2\u786e\u8ba4\u3002"}</p>
      )}

      {errors.map((item, index) => {
        if (acknowledged[index]) return null;
        const soft = generationErrorIsSoft(item);
        const open = Boolean(expanded[index]);
        const reason = generationErrorDetail(item);
        return (
          <div key={index} className={`rounded-xl border px-4 py-3 text-sm leading-6 ${soft ? "border-amber-300/30 bg-amber-300/10 text-amber-50" : "border-red-400/40 bg-red-400/15 text-red-50"}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="font-semibold">{generationErrorTitle(item)}</p>
                {reason ? <p className="mt-1 text-xs leading-5 opacity-80">{reason}</p> : null}
              </div>
              <button className="inline-flex shrink-0 items-center gap-1 rounded-full bg-white/10 px-3 py-1.5 text-xs font-semibold transition hover:bg-white/20" onClick={() => setExpanded((current) => ({ ...current, [index]: !current[index] }))} type="button">
                {open ? "\u6536\u8d77\u8be6\u60c5" : "\u67e5\u770b\u8be6\u60c5"}{open ? <ArrowUp size={14} strokeWidth={2} /> : <ArrowDown size={14} strokeWidth={2} />}
              </button>
            </div>
            {open ? (
              <div className="mt-3 grid gap-2 rounded-lg bg-black/20 p-3 text-xs leading-5">
                <p><span className="font-semibold">{"\u5931\u8d25\u539f\u56e0\uff1a"}</span>{reason || "\u672a\u77e5"}</p>
                <p><span className="font-semibold">{"\u5931\u8d25\u9636\u6bb5\uff1a"}</span>{stageLabel(item.stage)}</p>
                <p><span className="font-semibold">{"\u5931\u8d25\u65f6\u95f4\uff1a"}</span>{formatErrorTime(item.timestamp)}</p>
                {item.raw_error ? (
                  <details className="mt-1">
                    <summary className="cursor-pointer font-semibold text-white/70">{"\u539f\u59cb\u9519\u8bef\uff08\u6280\u672f\u6392\u67e5\uff09"}</summary>
                    <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all rounded bg-black/30 p-2 font-mono text-[11px] leading-5 text-white/70">{String(item.raw_error)}</pre>
                  </details>
                ) : null}
              </div>
            ) : null}
            <div className="mt-3 flex gap-2">
              <button className="rounded-full bg-white/10 px-3 py-1.5 text-xs font-semibold transition hover:bg-white/20" onClick={() => setAcknowledged((current) => ({ ...current, [index]: true }))} type="button">{"\u77e5\u9053\u4e86"}</button>
              <button className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[#192837] transition hover:bg-[#B99DFF]" onClick={onRegenerate} type="button">{"\u91cd\u65b0\u751f\u6210"}</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// \u2500\u2500 \u4e09\u671f-2\uff1a\u8584\u5f31\u70b9\u8bca\u65ad\u589e\u5f3a + \u5b66\u4e60\u8def\u5f84\u56fe\u8c31\uff08\u786e\u5b9a\u6027\u89c4\u5219\uff0c\u4e0d\u8c03 LLM\uff09\u2500\u2500

const priorityOrder = ["critical", "high", "medium", "low"];
const priorityRank = (priority?: string) => {
  const index = priorityOrder.indexOf((priority ?? "").toLowerCase());
  return index < 0 ? priorityOrder.length : index;
};

const priorityBadge = (priority?: string) => {
  switch ((priority ?? "").toLowerCase()) {
    case "critical": return { label: "\u5173\u952e", className: "bg-red-500/90 text-white" };
    case "high": return { label: "\u9ad8", className: "bg-orange-500/90 text-white" };
    case "medium": return { label: "\u4e2d", className: "bg-amber-400/90 text-[#192837]" };
    default: return { label: priority || "\u5f85\u5b9a", className: "bg-white/15 text-white/70" };
  }
};

const levelWeight: Record<string, number> = { core: 0, high: 1, standard: 2 };
const levelLabel = (level?: string) => {
  switch ((level ?? "").toLowerCase()) {
    case "core": return "\u6838\u5fc3";
    case "high": return "\u8fdb\u9636";
    case "standard": return "\u6807\u51c6";
    default: return level || "\u77e5\u8bc6\u70b9";
  }
};

const pct = (value?: number) => `${Math.round(Math.max(0, Math.min(1, value ?? 0)) * 100)}%`;

const sourceDocLabel = (path: string) => {
  const name = path.split("/").pop() ?? path;
  return name.replace(/\.md$/i, "");
};

function annotatePoint(point: KnowledgePoint, gaps: SkillGap[]): KnowledgePointView {
  const tokens = [point.topic ?? "", ...(point.aliases ?? [])]
    .map((token) => token.trim().toLowerCase())
    .filter(Boolean);
  let matched: SkillGap | undefined;
  for (const gap of gaps) {
    const gapTopic = (gap.topic ?? "").trim().toLowerCase();
    if (!gapTopic) continue;
    const hit = tokens.some((token) => token && (token.includes(gapTopic) || gapTopic.includes(token)));
    if (hit && (!matched || priorityRank(gap.priority) < priorityRank(matched.priority))) {
      matched = gap;
    }
  }
  if (!matched) return { ...point };
  return {
    ...point,
    is_weak: true,
    mastery: matched.current_level,
    target: matched.target_level,
    priority: matched.priority,
    reason: matched.reason,
  };
}

function buildLearningPath(
  coreMap: CoreMap | null,
  skillGaps: SkillGap[] | undefined,
): Array<{ domain: KnowledgeDomain; points: KnowledgePointView[] }> {
  const gaps = skillGaps ?? [];
  return (coreMap?.domains ?? []).map((domain) => {
    const points = (domain.knowledge_points ?? [])
      .map((point) => annotatePoint(point, gaps))
      .sort((a, b) => (levelWeight[a.level ?? ""] ?? 3) - (levelWeight[b.level ?? ""] ?? 3));
    return { domain, points };
  });
}

function SkillGapCards({ gaps, dark }: { gaps: SkillGap[]; dark?: boolean }) {
  return (
    <ul className="grid gap-2">
      {gaps.map((gap, index) => {
        const badge = priorityBadge(gap.priority);
        const hasLevels = typeof gap.current_level === "number" || typeof gap.target_level === "number";
        return (
          <li key={`${gap.topic}-${index}`} className={`rounded-xl px-4 py-3 ${dark ? "bg-white/[0.08]" : "bg-white/70"}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className={`text-sm font-medium ${dark ? "text-white/90" : "text-[#192837]"}`}>{gap.topic || "\u5f85\u8865\u5145\u77e5\u8bc6\u70b9"}</span>
              {gap.priority ? <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${badge.className}`}>{badge.label}</span> : null}
            </div>
            {hasLevels ? (
              <div className="mt-2">
                <div className={`flex items-center justify-between text-xs ${dark ? "text-white/55" : "text-[#192837]/55"}`}>
                  <span>{"\u638c\u63e1\u5ea6"} {typeof gap.current_level === "number" ? pct(gap.current_level) : "\u2014"}</span>
                  <span>{"\u76ee\u6807"} {typeof gap.target_level === "number" ? pct(gap.target_level) : "\u2014"}</span>
                </div>
                <div className={`mt-1 h-1.5 rounded-full ${dark ? "bg-white/10" : "bg-[#192837]/10"}`}>
                  <div className="h-full rounded-full bg-[#7342E2]" style={{ width: typeof gap.current_level === "number" ? pct(gap.current_level) : "0%" }} />
                </div>
              </div>
            ) : null}
            {gap.reason ? <p className={`mt-2 text-xs leading-5 ${dark ? "text-white/55" : "text-[#192837]/55"}`}>{gap.reason}</p> : null}
          </li>
        );
      })}
    </ul>
  );
}

function LearningPathMap({ groups }: { groups: Array<{ domain: KnowledgeDomain; points: KnowledgePointView[] }> }) {
  if (!groups.length) return null;
  const total = groups.reduce((sum, group) => sum + group.points.length, 0);
  return (
    <div className="mt-6 rounded-2xl border border-white/10 bg-white/[0.04] p-4 sm:p-5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-white/70">{"\u5b66\u4e60\u8def\u5f84\u56fe\u8c31 \u00b7 \u6838\u5fc3\u77e5\u8bc6\u4f53\u7cfb"}</p>
        <span className="text-xs text-white/45">{groups.length} {"\u9886\u57df"} {"\u00b7"} {total} {"\u77e5\u8bc6\u70b9"}</span>
      </div>
      <div className="mt-4 grid gap-5">
        {groups.map(({ domain, points }) => (
          <div key={domain.id ?? domain.name}>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-[#7342E2]/25 px-2 py-0.5 text-xs font-semibold text-[#C7B3F5]">{domain.id}</span>
              <ArrowRight size={13} strokeWidth={2} className="text-white/30" />
              <span className="text-sm font-semibold text-white/85">{domain.name}</span>
              <span className="text-xs text-white/40">{points.length}</span>
            </div>
            <div className="mt-2 flex flex-col gap-1.5 border-l border-white/15 pl-3">
              {points.map((point, index) => {
                const badge = priorityBadge(point.priority);
                const isWeak = !!point.is_weak;
                return (
                  <div key={point.id ?? `${domain.id}-${index}`}>
                    {index > 0 ? <div className="flex justify-center py-0.5 text-white/25"><ArrowDown size={14} strokeWidth={2} /></div> : null}
                    <div className={`rounded-lg px-3 py-2 ${isWeak ? "border border-[#7342E2]/40 bg-[#7342E2]/10" : "bg-white/[0.05]"}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-start gap-1.5">
                        <span className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold ${levelWeight[point.level ?? ""] === 0 ? "bg-[#7342E2]/30 text-[#C7B3F5]" : levelWeight[point.level ?? ""] === 1 ? "bg-sky-400/20 text-sky-200" : "bg-white/10 text-white/60"}`}>{levelLabel(point.level)}</span>
                        <span className="text-sm leading-5 text-white/90">{point.topic || "\u672a\u547d\u540d\u77e5\u8bc6\u70b9"}</span>
                      </div>
                      {isWeak && point.priority ? <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${badge.className}`}>{badge.label}</span> : null}
                    </div>
                    {isWeak ? (
                      <div className="mt-2">
                        <div className="flex items-center justify-between text-xs text-white/55">
                          <span>{"\u638c\u63e1\u5ea6"} {typeof point.mastery === "number" ? pct(point.mastery) : "\u2014"}</span>
                          <span>{"\u76ee\u6807"} {typeof point.target === "number" ? pct(point.target) : "\u2014"}</span>
                        </div>
                        <div className="mt-1 h-1.5 rounded-full bg-white/10">
                          <div className="h-full rounded-full bg-[#7342E2]" style={{ width: typeof point.mastery === "number" ? pct(point.mastery) : "0%" }} />
                        </div>
                        {point.reason ? <p className="mt-1.5 text-xs leading-5 text-white/55">{point.reason}</p> : null}
                      </div>
                    ) : null}
                    {point.source_documents && point.source_documents.length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {point.source_documents.map((doc) => (
                          <span key={doc} className="rounded bg-white/[0.07] px-1.5 py-0.5 text-[11px] text-white/45" title={doc}>
                            {sourceDocLabel(doc)}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const documentEntityMap: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

const escapeDocumentHtml = (value: string) => value.replace(/[&<>"']/g, (character) => documentEntityMap[character] ?? character);

const renderDocumentInline = (value: string) => escapeDocumentHtml(value)
  .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
  // WPS imports HTML <code> tags in .doc files as outlined compatibility fields.
  // Keep the term itself, but export it as ordinary text.
  .replace(/`([^`]+)`/g, "$1");

const renderDocumentMarkdown = (value: string) => {
  const lines = value.replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let listKind: "ol" | "ul" | null = null;
  let listItems: string[] = [];
  let codeLines: string[] = [];
  let inCodeBlock = false;
  const flushList = () => {
    if (!listKind) return;
    output.push(`<${listKind}>${listItems.map((item) => `<li>${renderDocumentInline(item)}</li>`).join("")}</${listKind}>`);
    listKind = null;
    listItems = [];
  };
  const flushCode = () => {
    if (!inCodeBlock) return;
    output.push(`<pre style="background:#172b3a;color:#f7f8fa;border-radius:8pt;line-height:1.55;margin:12pt 0;overflow-wrap:anywhere;padding:12pt"><code>${escapeDocumentHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trim();
    if (/^```/.test(line)) {
      if (inCodeBlock) flushCode(); else flushList();
      inCodeBlock = !inCodeBlock;
      return;
    }
    if (inCodeBlock) {
      codeLines.push(rawLine);
      return;
    }
    if (!line) {
      flushList();
      return;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushList();
      const level = Math.min(heading[1].length + 1, 5);
      output.push(`<h${level}>${renderDocumentInline(heading[2])}</h${level}>`);
      return;
    }
    const ordered = line.match(/^\d+[.、)]\s+(.+)$/);
    const unordered = line.match(/^[-*+]\s+(.+)$/);
    if (ordered || unordered) {
      const nextKind = ordered ? "ol" : "ul";
      if (listKind && listKind !== nextKind) flushList();
      listKind = nextKind;
      listItems.push((ordered ?? unordered)?.[1] ?? line);
      return;
    }
    flushList();
    const safetyWarning = line.match(/^>\s*(?:⚠️\s*)?安全提示[:：]\s*(.*)$/);
    if (safetyWarning) {
      output.push(`<p style="background:#fdecea;color:#b3261e;border-left:4pt solid #b3261e;margin:12pt 0;padding:9pt 12pt">⚠️ ${renderDocumentInline(safetyWarning[1])}</p>`);
      return;
    }
    if (line.startsWith(">")) {
      output.push(`<p style="background:#f5f5f5;color:#40505c;margin:12pt 0;padding:9pt 12pt">${renderDocumentInline(line.replace(/^>\s?/, ""))}</p>`);
      return;
    }
    output.push(`<p>${renderDocumentInline(line)}</p>`);
  });
  if (inCodeBlock) flushCode();
  flushList();
  return output.length ? output.join("") : "<p>\u6682\u65e0\u5185\u5bb9\u3002</p>";
};

const renderDocumentParagraphs = (value: string) => {
  const paragraphs = value
    .replace(/\r\n?/g, "\n")
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);

  return paragraphs.length
    ? paragraphs.map((paragraph) => `<p>${escapeDocumentHtml(paragraph).replace(/\n/g, "<br />")}</p>`).join("")
    : "<p>暂无正文内容。</p>";
};

const renderQuizDocument = (quiz: Quiz) => `
  <section class="quiz">
    <h3>${escapeDocumentHtml(quiz.title)}</h3>
    ${quiz.questions.map((question, index) => `
      <article class="question">
        <h4>${index + 1}. ${escapeDocumentHtml(question.stem)}</h4>
        ${question.options.length ? `<ol type="A">${question.options.map((option) => `<li>${escapeDocumentHtml(option.text)}</li>`).join("")}</ol>` : ""}
        <p><strong>参考答案：</strong>${escapeDocumentHtml(question.answer || "未提供")}</p>
        <p><strong>解析：</strong>${escapeDocumentHtml(question.explanation || "未提供")}</p>
      </article>
    `).join("")}
  </section>
`;

const renderQuizDocumentForExport = (quiz: Quiz) => `
  <section class="quiz">
    <h3>${escapeDocumentHtml(quiz.title)}</h3>
    ${quiz.questions.map((question, index) => `
      <article class="question">
        <h4>${index + 1}. ${escapeDocumentHtml(question.stem)}</h4>
        ${question.options.length ? `<ol type="A">${question.options.map((option) => `<li>${escapeDocumentHtml(option.text)}</li>`).join("")}</ol>` : ""}
        <div style="background:#f5f2ff;border-left:4px solid #7342e2;margin-top:12pt;padding:9pt 12pt">
          <p><strong>\u53c2\u8003\u7b54\u6848\uff1a</strong>${escapeDocumentHtml(question.answer || "\u672c\u9898\u7b54\u6848\u952e\u672a\u968f\u8d44\u6e90\u8fd4\u56de\uff0c\u8bf7\u91cd\u65b0\u751f\u6210\u8be5\u8d44\u6e90\u3002")}</p>
          <p><strong>\u7b54\u6848\u89e3\u6790\uff1a</strong>${escapeDocumentHtml(question.explanation || "\u672c\u9898\u89e3\u6790\u672a\u968f\u8d44\u6e90\u8fd4\u56de\uff0c\u8bf7\u91cd\u65b0\u751f\u6210\u8be5\u8d44\u6e90\u3002")}</p>
        </div>
      </article>
    `).join("")}
  </section>
`;

const quizSignalPattern = /\b(?:quiz|exam|test|assessment|questionnaire)\b|\u6d4b\u8bd5\u9898|\u9009\u62e9\u9898|\u586b\u7a7a\u9898|\u6807\u51c6\u7b54\u6848|\u53c2\u8003\u7b54\u6848|\u6b63\u786e\u7b54\u6848|\u7b54\u6848\u89e3\u6790|\u89e3\u6790/u;
const quizOptionPattern = /^\s*(?:[-*]\s*)?(?:[\(\uFF08]\s*)?([A-D])\s*(?:[\)\uFF09]\s*|[.\uFF0E\u3001:\uFF1A\]]\s*)(.+)$/i;
const quizQuestionPattern = /^\s*(?:#{1,6}\s*)?(?:(?:\u7b2c\s*[0-9\u4e00-\u9fff]+\s*\u9898)|(?:\u9898\u76ee|\u95ee\u9898)\s*\d*|Q(?:uestion)?\s*\d+|[0-9\u4e00-\u9fff]+\s*[.\uFF0E\u3001)])\s*[:\uFF1A.]?/i;
const quizAnswerPattern = /(?:\u6807\u51c6\u7b54\u6848|\u53c2\u8003\u7b54\u6848|\u6b63\u786e\u7b54\u6848|\u7b54\u6848(?!\u89e3\u6790)|answer)\s*(?:is|\u662f|\u4e3a|\u9009)?\s*[:\uFF1A=]?\s*(.+)/i;
const quizExplanationPattern = /(?:\u7b54\u6848\u89e3\u6790|\u89e3\u6790|explanation)\s*[:\uFF1A=]?\s*(.+)/i;

function decodeEscapedText(value: string) {
  let decoded = value;
  for (let pass = 0; pass < 8; pass += 1) {
    const next = decoded
      .replace(/\\+u([0-9a-f]{4})/gi, (_match, code: string) => String.fromCharCode(Number.parseInt(code, 16)))
      .replace(/\\+n/g, "\n");
    if (next === decoded) break;
    decoded = next;
  }
  return decoded;
}

function decodeApiText<T>(value: T): T {
  if (typeof value === "string") return decodeEscapedText(value) as T;
  if (Array.isArray(value)) return value.map((item) => decodeApiText(item)) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, nestedValue]) => [decodeEscapedText(key), decodeApiText(nestedValue)]),
    ) as T;
  }
  return value;
}

function generationTaskErrorMessage(error: unknown) {
  const message = decodeEscapedText(error instanceof Error ? error.message : String(error ?? "")).trim();
  if (/connection error|api connection|network error|llm.*(?:error|fail)|模型.*(?:连接|服务)/i.test(message)) {
    return "模型服务连接失败，下一轮测试尚未生成。请检查后端的 LLM 地址、网络和 API Key 后重试。";
  }
  return message || "下一轮针对性测试生成失败，请稍后重试。";
}

function cleanQuizLine(value: string) {
  return value.replace(/^\s*(?:[-*]\s*)?/, "").replace(/\*\*/g, "").replace(/^#{1,6}\s*/, "").trim();
}

function hasQuizSignals(resource: GeneratedResource) {
  const explicitType = resource.resource_type?.trim().toLowerCase();
  if (explicitType && !isQuizResourceType(explicitType)) return false;
  const content = resource.content ?? "";
  const identity = `${resource.resource_type} ${resource.title} ${content}`.toLowerCase();
  const optionCount = content.split("\n").filter((line) => quizOptionPattern.test(line)).length;
  return Boolean(resource.quiz?.questions.length) || optionCount >= 2 || quizSignalPattern.test(identity);
}

function hasCompleteChoiceOptions(options: Quiz["questions"][number]["options"]) {
  const ids = new Set(options.map((option) => option.id.toUpperCase()));
  return options.length === 4 && ["A", "B", "C", "D"].every((id) => ids.has(id));
}

function hasClearQuizStem(stem: string) {
  const normalized = cleanQuizLine(stem).replace(quizQuestionPattern, "").trim();
  if (normalized.replace(/\s/g, "").length < 4) return false;
  if (/^[^?\uFF1F]{1,80}[\(\uFF08](?:\u57FA\u7840|\u8FDB\u9636|\u573A\u666F|\u5B9E\u64CD|\u6311\u6218)?(?:\u9009\u62E9\u9898|\u7B80\u7B54\u9898|\u586B\u7A7A\u9898|\u5E94\u7528\u9898)?[\)\uFF09]$/.test(normalized)) return false;
  return /[?\uFF1F]|\b(?:which|what|how|why|when|where|should|can|does|describe|select|identify|choose|explain|state|list)\b|(?:\u4EE5\u4E0B|\u54EA(?:\u4E2A|\u9879|\u79CD)|\u4EC0\u4E48|\u5982\u4F55|\u4E3A\u4EC0\u4E48|\u662F\u5426|\u8BF7(?:\u9009\u62E9|\u5224\u65AD|\u8BF4\u660E|\u5199\u51FA|\u5217\u51FA|\u56DE\u7B54)|\u5E94(?:\u8BE5|\u5F53)|\u6B63\u786E|\u9519\u8BEF|\u6B65\u9AA4|\u539F\u56E0|\u64CD\u4F5C|\u5904\u7406|\u5224\u65AD)/i.test(normalized);
}

function isUsableQuizQuestion(question: Quiz["questions"][number]) {
  if (!hasClearQuizStem(question.stem)) return false;
  if (!question.answer.trim() || !question.explanation.trim()) return false;
  return !question.options.length || hasCompleteChoiceOptions(question.options);
}

function normalizeQuiz(quiz: Quiz): Quiz | null {
  const questions = quiz.questions.filter(isUsableQuizQuestion);
  return questions.length >= 5 ? { ...quiz, questions } : null;
}

function decodeQuizText(quiz: Quiz): Quiz {
  return {
    ...quiz,
    title: decodeEscapedText(quiz.title),
    questions: quiz.questions.map((question) => ({
      ...question,
      stem: decodeEscapedText(question.stem),
      options: question.options.map((option) => ({ ...option, text: decodeEscapedText(option.text) })),
      answer: decodeEscapedText(question.answer),
      explanation: decodeEscapedText(question.explanation),
    })),
  };
}

function parseQuizContent(resource: GeneratedResource): Quiz | null {
  const content = decodeEscapedText(resource.content ?? "");
  if (!content.trim()) return null;

  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const starts = lines.reduce<number[]>((indexes, line, index) => {
    if (quizQuestionPattern.test(line)) indexes.push(index);
    return indexes;
  }, []);
  const questionStarts = starts.length ? starts : [0];
  const questions: Quiz["questions"] = [];

  questionStarts.forEach((start, index) => {
    const end = questionStarts[index + 1] ?? lines.length;
    const block = lines.slice(start, end).map(cleanQuizLine).filter(Boolean);
    const options = block.map((line) => {
      const match = line.match(quizOptionPattern);
      return match ? { id: match[1].toUpperCase(), text: match[2].trim() } : null;
    }).filter((item): item is { id: string; text: string } => item !== null);
    const answerLine = block.find((line) => quizAnswerPattern.test(line));
    const explanationLine = block.find((line) => quizExplanationPattern.test(line));
    const questionLine = block.find((line) => {
      const clean = cleanQuizLine(line);
      return !quizOptionPattern.test(clean)
        && !quizAnswerPattern.test(clean)
        && !quizExplanationPattern.test(clean)
        && (quizQuestionPattern.test(clean) || block.indexOf(line) === 0);
    });
    if (!questionLine) return;

    const answer = answerLine?.match(quizAnswerPattern)?.[1]?.trim() ?? "";
    const explanation = explanationLine?.match(quizExplanationPattern)?.[1]?.trim() ?? "";
    const stem = cleanQuizLine(questionLine).replace(quizQuestionPattern, "").trim() || cleanQuizLine(questionLine);
    const isChoice = hasCompleteChoiceOptions(options);
    if (!hasClearQuizStem(stem) || (options.length && !isChoice)) return;
    questions.push({
      id: `parsed-q${index + 1}`,
      stem,
      options: isChoice ? options : [],
      answer,
      explanation,
      questionType: isChoice ? "choice" : "fill",
    });
  });

  return normalizeQuiz({ title: resource.title, questions });

  // Legacy recovery deliberately disabled: it invented stems for malformed
  // option groups and could turn a section title into a question.
  if (false) {
  const normalizedQuestions = questions.flatMap((question) => {
    // A malformed model response can omit later headings and repeat A-D.
    // Recover each complete option group as its own question instead of
    // rendering every option in one oversized question.
    if (question.options.length <= 4) return [question];

    const optionGroups: Array<typeof question.options> = [];
    let group: typeof question.options = [];
    question.options.forEach((option) => {
      if (option.id === "A" && group.length) {
        optionGroups.push(group);
        group = [];
      }
      group.push(option);
    });
    if (group.length) optionGroups.push(group);

    return optionGroups.map((options, groupIndex) => ({
      ...question,
      id: `${question.id}-${groupIndex + 1}`,
      stem: groupIndex === 0
        ? question.stem
        : `\u7b2c ${groupIndex + 1} \u5c0f\u9898\uff1a\u8bf7\u6839\u636e\u4ee5\u4e0b\u9009\u9879\u4f5c\u7b54\u3002`,
      options,
      // A trailing answer key cannot be mapped safely to recovered groups.
      answer: groupIndex === 0 ? question.answer : "",
      explanation: groupIndex === 0 ? question.explanation : "",
    }));
  });

  return normalizedQuestions.length ? { title: resource.title, questions: normalizedQuestions } : null;
  }
}

function isQuizResource(resource: GeneratedResource) {
  const explicitType = resource.resource_type?.trim().toLowerCase();
  if (explicitType) return isQuizResourceType(explicitType);
  if (hasQuizSignals(resource)) return true;
  const identity = `${resource.resource_type} ${resource.title} ${resource.content ?? ""}`.toLowerCase();
  const optionLineCount = (resource.content ?? "").match(/^\s*[A-D][.:]\s+/gim)?.length ?? 0;
  if (optionLineCount >= 2) return true;
  return /\b(quiz|exam|test|assessment)\b|测试题|测验|自测|标准答案|题目\s*\d+|第\s*[一二三四五六七八九十\d]+\s*题/.test(identity);
}

function workspaceResourceItems(resources: GeneratedResource[]) {
  let hasQuiz = false;
  return resources.filter((resource) => {
    if (!isQuizResource(resource)) return true;
    if (hasQuiz) return false;
    hasQuiz = true;
    return true;
  });
}

function quizRoundNumber(resources: GeneratedResource[], resource: GeneratedResource) {
  const resourceIndex = resources.indexOf(resource);
  const throughCurrent = resourceIndex >= 0 ? resources.slice(0, resourceIndex + 1) : resources;
  return Math.max(1, throughCurrent.filter(isQuizResource).length);
}

function quizFromResource(resource: GeneratedResource, topic: string): Quiz | null {
  if (resource.quiz?.questions.length) return normalizeQuiz(decodeQuizText(resource.quiz));
  const parsedQuiz = parseQuizContent(resource);
  if (parsedQuiz?.questions.length) return parsedQuiz;

  return null;

  // Legacy fallback deliberately disabled: malformed quiz text must be
  // regenerated rather than replaced by a demo quiz.
  if (false) {
  const content = resource.content ?? "";
  const blocks = content.split(/(?=^\s*(?:#{1,6}\s*)?(?:第\s*[一二三四五六七八九十\d]+\s*题|题目\s*\d+|Q\s*\d+))/im);
  const questions: Quiz["questions"] = [];
  blocks.forEach((block, index) => {
    const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
    const options = lines.map((line) => {
      const match = line.match(/^([A-D])[.、:：]\s*(.+)$/i);
      return match ? { id: match[1].toUpperCase(), text: match[2] } : null;
    }).filter((item): item is { id: string; text: string } => item !== null);
    const firstQuestionLine = lines.find((line) => /[？?]$/.test(line) || /^问题[：:]/.test(line)) ?? lines[1] ?? lines[0];
    const answer = block.match(/(?:标准答案|答案)\s*[：:]\s*([A-D]|[^\n]+)/i)?.[1]?.trim() ?? "";
    const explanation = block.match(/(?:解析|说明)\s*[：:]\s*([^\n]+(?:\n(?!\s*(?:第\s*[一二三四五六七八九十\d]+\s*题|题目\s*\d+|Q\s*\d+)).*)*)/i)?.[1]?.trim() ?? "";
    if (!firstQuestionLine || !options.length) return;
    questions.push({
      id: `generated-q${index + 1}`,
      stem: firstQuestionLine.replace(/^问题[：:]\s*/, ""),
      options,
      answer,
      explanation,
      questionType: "choice" as const,
    });
  });

  return questions.length ? { title: resource.title || `${topic} 测试题`, questions } : createDemoQuiz(topic);
  }
}

const qualityGates: Array<{ id: QualityGate; label: string }> = [
  { id: "evidence", label: "依据校验" },
  { id: "difficulty", label: "难度匹配" },
  { id: "expression", label: "表达审核" },
];

function renderInlineMarkdown(value: string) {
  return value.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong className="font-semibold text-white" key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code className="rounded-md bg-white/10 px-1.5 py-0.5 font-mono text-[0.86em] text-white" key={index}>{part.slice(1, -1)}</code>;
    }
    return part;
  });
}

function LookupChips({ instruction_links, alarm_links }: {
  instruction_links?: GeneratedResource["instruction_links"];
  alarm_links?: GeneratedResource["alarm_links"];
}) {
  const instructionChips = (instruction_links ?? []).filter((l) => l?.name && l?.brand);
  const alarmChips = (alarm_links ?? []).filter((l) => l?.code && l?.brand);
  if (!instructionChips.length && !alarmChips.length) return null;
  return (
    <div className="mt-4 rounded-xl bg-white/[0.07] px-4 py-3 text-xs leading-6 text-white/70">
      <span className="font-semibold text-white/85">关联速查</span>
      <div className="mt-2 flex flex-wrap gap-2">
        {instructionChips.map((l, i) => (
          <a
            key={`ins-${i}`}
            href={`/api/knowledge/instructions/${l.brand}/${encodeURIComponent(l.name!)}`}
            target="_blank"
            rel="noreferrer"
            title={l.doc_title}
            className="rounded-full border border-white/15 bg-white/[0.06] px-3 py-1 text-xs text-white/85 transition hover:bg-white/[0.14]"
          >
            {l.name}（{l.brand}）
          </a>
        ))}
        {alarmChips.map((l, i) => (
          <a
            key={`alm-${i}`}
            href={`/api/knowledge/alarms/${l.brand}/${encodeURIComponent(l.code!)}`}
            target="_blank"
            rel="noreferrer"
            title={l.doc_title}
            className="rounded-full border border-white/15 bg-white/[0.06] px-3 py-1 text-xs text-white/85 transition hover:bg-white/[0.14]"
          >
            {l.code}（{l.brand}）
          </a>
        ))}
      </div>
    </div>
  );
}

function RiskBanner({ level }: { level?: string }) {
  if (level === "high_risk") {
    return (
      <div className="mt-6 flex items-start gap-3 rounded-2xl border border-red-400/30 bg-red-400/15 px-4 py-3 text-sm leading-7 text-red-50">
        <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" />
        <span>{"⚠️ 工业实操有风险，请勿未经培训操作真机。操作前请阅读并遵守本课程的「安全操作确认清单」。"}</span>
      </div>
    );
  }
  if (level === "low_risk") {
    return (
      <div className="mt-6 flex items-start gap-3 rounded-2xl border border-amber-300/30 bg-amber-300/15 px-4 py-3 text-sm leading-7 text-amber-50">
        <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" />
        <span>{"⚠️ 本内容涉及软件操作与参数设置，操作前请确认已备份参数，避免误改影响生产运行。"}</span>
      </div>
    );
  }
  return null;
}


type GlobalAlarmHit = { brand?: string; alarm_code?: string; fault_name?: string; symptom?: string; doc_id?: string; doc_title?: string };
type GlobalInstructionHit = { brand?: string; instruction?: string; doc_id?: string; doc_title?: string };
type GlobalDocumentHit = { doc_id?: string; doc_title?: string; content?: string };

const BRAND_ALIASES: Array<[string, string]> = [
  ["库卡", "kuka"],
  ["发那科", "fanuc"],
  ["法兰克", "fanuc"],
  ["安川", "yaskawa"],
  ["优傲", "ur"],
];

function expandQueryForMatch(q: string): string[] {
  const lower = q.toLowerCase();
  const terms = [lower];
  for (const [zh, en] of BRAND_ALIASES) {
    if (lower.includes(zh) && !lower.includes(en)) terms.push(en);
    else if (lower.includes(en) && !lower.includes(zh)) terms.push(zh);
  }
  return terms;
}

function globalMatch(haystack: string, q: string): boolean {
  const hay = haystack.toLowerCase();
  return expandQueryForMatch(q).some((term) => hay.includes(term));
}

type DocumentDetail = { title: string; content: string; source: string };

function DocumentDetailModal({ detail, onClose }: { detail: DocumentDetail | null; onClose: () => void }) {
  if (!detail) return null;
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4 sm:p-8">
      <button aria-label={"关闭详情"} className="absolute inset-0 bg-[#192837]/40 backdrop-blur-[4px]" onClick={onClose} type="button" />
      <div className="relative flex max-h-[85dvh] w-full max-w-[720px] flex-col overflow-hidden rounded-[1.75rem] bg-[#F2F2EE] shadow-[0_28px_100px_rgba(25,40,55,0.34)]">
        <div className="flex items-start justify-between gap-4 border-b border-[#192837]/10 px-6 py-5 sm:px-8">
          <div className="min-w-0">
            <p className="truncate text-xs font-semibold tracking-[0.12em] text-[#192837]/50">{detail.source}</p>
            <h2 className="mt-1 truncate font-[var(--font-heading)] text-xl leading-tight text-[#192837]">{detail.title}</h2>
          </div>
          <button aria-label={"关闭"} className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#192837]/[0.08] transition hover:bg-[#192837]/[0.15]" onClick={onClose} type="button"><X size={20} strokeWidth={1.8} /></button>
        </div>
        <div className="overflow-y-auto px-6 py-5 text-sm leading-7 text-[#192837]/80 [&_h2]:mt-5 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:text-[#192837] [&_h3]:mt-4 [&_h3]:text-lg [&_h3]:font-semibold [&_h3]:text-[#192837] [&_h4]:mt-3 [&_h4]:font-semibold [&_h4]:text-[#192837] [&_p]:my-2 [&_ul]:my-3 [&_ol]:my-3 [&_li]:my-1 sm:px-8" dangerouslySetInnerHTML={{ __html: renderDocumentMarkdown(detail.content) }} />
      </div>
    </div>
  );
}

function References({ citations }: { citations?: GeneratedResource["citations"] }) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const seen = new Set<string>();
  const refs = (citations ?? []).filter((c) => {
    const id = c?.doc_id;
    if (!id || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  if (!refs.length) return null;
  async function openDoc(doc_id: string, doc_title: string) {
    try {
      const res = await fetch(`${getApiBase()}/api/knowledge/documents/${encodeURIComponent(doc_id)}`);
      const data = res.ok ? await res.json() : null;
      setDetail({ title: data?.title || doc_title || doc_id, content: data?.content || "加载失败，请稍后重试。", source: "知识文档" });
    } catch {
      setDetail({ title: doc_title || doc_id, content: "加载失败，请稍后重试。", source: "知识文档" });
    }
  }
  return (
    <>
      <div className="mt-4 rounded-xl bg-white/[0.07] px-4 py-3 text-xs leading-6 text-white/70">
        <span className="font-semibold text-white/85">{"参考文档"}</span>
        <div className="mt-2 flex flex-col gap-0.5">
          {refs.map((c, i) => (
            <button key={`cite-${i}`} onClick={() => openDoc(c.doc_id ?? "", c.doc_title ?? "")} className="group flex items-start gap-2 rounded-lg px-2 py-1 text-left transition hover:bg-white/[0.06]" type="button">
              <ArrowRight className="mt-1 h-3.5 w-3.5 shrink-0 text-white/40" />
              <span className="min-w-0">
                <span className="block truncate text-white/85 group-hover:text-white">{c.doc_title || c.doc_id}</span>
                {c.original_text ? <span className="mt-0.5 block truncate text-white/45">{c.original_text}</span> : null}
              </span>
            </button>
          ))}
        </div>
      </div>
      <DocumentDetailModal detail={detail} onClose={() => setDetail(null)} />
    </>
  );
}

function GlobalSearch() {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [alarmIndex, setAlarmIndex] = useState<GlobalAlarmHit[]>([]);
  const [instructionIndex, setInstructionIndex] = useState<GlobalInstructionHit[]>([]);
  const [docHits, setDocHits] = useState<GlobalDocumentHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch(`${getApiBase()}/api/knowledge/alarms`).then((r) => (r.ok ? r.json() : null)),
      fetch(`${getApiBase()}/api/knowledge/instructions`).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([alarms, instructions]) => {
        if (cancelled) return;
        setAlarmIndex(alarms?.entries ?? []);
        setInstructionIndex(instructions?.entries ?? []);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setOpen(false);
      setDocHits([]);
      return;
    }
    setOpen(true);
    const timer = window.setTimeout(async () => {
      setSearching(true);
      try {
        const res = await fetch(`${getApiBase()}/api/knowledge/search?q=${encodeURIComponent(q)}&top_k=5`);
        const data = res.ok ? await res.json() : null;
        setDocHits(data?.results ?? []);
      } catch {
        setDocHits([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    function onDocClick(event: Event) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  async function openDetail(path: string, fallbackTitle: string, source: string) {
    setOpen(false);
    try {
      const res = await fetch(`${getApiBase()}${path}`);
      const data = res.ok ? await res.json() : null;
      setDetail({
        title: data?.title || data?.doc_title || fallbackTitle,
        content: data?.content || "加载失败，请稍后重试。",
        source,
      });
    } catch {
      setDetail({ title: fallbackTitle, content: "加载失败，请稍后重试。", source });
    }
  }

  const q = query.trim();
  const ql = q.toLowerCase();
  const alarmHits = ql
    ? alarmIndex
        .filter((e) => globalMatch([e.brand, e.alarm_code, e.fault_name, e.symptom, e.doc_title].filter(Boolean).join(" "), ql))
        .slice(0, 5)
    : [];
  const instructionHits = ql
    ? instructionIndex
        .filter((e) => globalMatch([e.brand, e.instruction, e.doc_title].filter(Boolean).join(" "), ql))
        .slice(0, 5)
    : [];
  const hasResults = alarmHits.length > 0 || instructionHits.length > 0 || docHits.length > 0;

  return (
    <div ref={containerRef} className="relative hidden min-w-0 flex-1 max-w-sm lg:block">
      <div className="flex items-center gap-2 rounded-full bg-[#192837]/[0.06] px-4 py-2">
        <Search className="h-4 w-4 shrink-0 text-[#192837]/50" />
        <input
          className="w-full bg-transparent text-sm text-[#192837] outline-none placeholder:text-[#192837]/45"
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => { if (query.trim()) setOpen(true); }}
          placeholder="全局搜索：报警 / 指令 / 知识文档"
          type="text"
          value={query}
        />
        {query ? <button className="grid h-5 w-5 place-items-center rounded-full text-[#192837]/45 hover:bg-[#192837]/10" onClick={() => { setQuery(""); setOpen(false); }} type="button"><X size={14} strokeWidth={1.8} /></button> : null}
      </div>
      {open && q ? (
        <div className="absolute left-0 right-0 top-full z-50 mt-2 max-h-[70vh] overflow-y-auto rounded-2xl border border-[#192837]/10 bg-white p-2 shadow-[0_18px_60px_rgba(25,40,55,0.18)]">
          {searching && !hasResults ? <p className="px-3 py-4 text-center text-sm text-[#192837]/55">{"搜索中…"}</p> : null}
          {!searching && !hasResults ? <p className="px-3 py-4 text-center text-sm text-[#192837]/55">{"未找到匹配内容"}</p> : null}
          {alarmHits.length ? (
            <div className="mt-1">
              <p className="px-3 py-2 text-xs font-semibold tracking-[0.12em] text-[#192837]/50">{"报警排查"}</p>
              {alarmHits.map((e, i) => (
                <button key={`alm-${i}`} onClick={() => openDetail(`/api/knowledge/alarms/${e.brand}/${encodeURIComponent(e.alarm_code ?? "")}`, e.alarm_code || e.fault_name || "报警文档", `${e.brand ?? ""} · ${e.alarm_code ?? ""}`)} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition hover:bg-[#192837]/[0.06]" type="button">
                  <span className="rounded-full bg-red-400/15 px-2 py-0.5 text-xs font-semibold text-red-600">{e.brand ?? ""}</span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold text-[#192837]">{e.alarm_code}</span>
                    <span className="block truncate text-xs text-[#192837]/55">{e.fault_name || e.symptom || e.doc_title}</span>
                  </span>
                </button>
              ))}
            </div>
          ) : null}
          {instructionHits.length ? (
            <div className="mt-2">
              <p className="px-3 py-2 text-xs font-semibold tracking-[0.12em] text-[#192837]/50">{"指令速查"}</p>
              {instructionHits.map((e, i) => (
                <button key={`ins-${i}`} onClick={() => openDetail(`/api/knowledge/instructions/${e.brand}/${encodeURIComponent(e.instruction ?? "")}`, e.instruction || "指令文档", `${e.brand ?? ""} · ${e.instruction ?? ""}`)} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition hover:bg-[#192837]/[0.06]" type="button">
                  <span className="rounded-full bg-amber-400/20 px-2 py-0.5 text-xs font-semibold text-amber-700">{e.brand ?? ""}</span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold text-[#192837]">{e.instruction}</span>
                    <span className="block truncate text-xs text-[#192837]/55">{e.doc_title}</span>
                  </span>
                </button>
              ))}
            </div>
          ) : null}
          {docHits.length ? (
            <div className="mt-2">
              <p className="px-3 py-2 text-xs font-semibold tracking-[0.12em] text-[#192837]/50">{"知识文档"}</p>
              {docHits.map((e, i) => (
                <button key={`doc-${i}`} onClick={() => openDetail(`/api/knowledge/documents/${encodeURIComponent(e.doc_id ?? "")}`, e.doc_title || e.doc_id || "知识文档", e.doc_title || e.doc_id || "知识文档")} className="block w-full rounded-xl px-3 py-2 text-left transition hover:bg-[#192837]/[0.06]" type="button">
                  <span className="block truncate text-sm font-semibold text-[#192837]">{e.doc_title || e.doc_id}</span>
                  <span className="block truncate text-xs text-[#192837]/55">{e.content}</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      <DocumentDetailModal detail={detail} onClose={() => setDetail(null)} />
    </div>
  );
}


function ResourceMarkdown({ content }: { content: string }) {
  const lines = decodeEscapedText(content).replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let lineIndex = 0;

  while (lineIndex < lines.length) {
    const line = lines[lineIndex].trim();
    if (!line) {
      lineIndex += 1;
      continue;
    }

    const fence = line.match(/^```([^\s]*)/);
    if (fence) {
      const code: string[] = [];
      lineIndex += 1;
      while (lineIndex < lines.length && !lines[lineIndex].trim().startsWith("```")) {
        code.push(lines[lineIndex]);
        lineIndex += 1;
      }
      if (lineIndex < lines.length) lineIndex += 1;
      blocks.push(
        <div className="my-6 overflow-hidden rounded-xl bg-black/30" key={`code-${lineIndex}`}>
          <div className="flex items-center justify-between bg-black/20 px-4 py-2 text-xs font-semibold text-white/55">
            <span>{fence[1] || "代码示例"}</span>
            <span>CODE</span>
          </div>
          <pre className="overflow-x-auto px-4 py-4 font-mono text-[0.82rem] leading-6 text-[#DCE9F6]"><code>{code.join("\n")}</code></pre>
        </div>,
      );
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const className = level === 1 ? "mt-9 text-2xl font-semibold leading-tight text-white" : level === 2 ? "mt-8 text-xl font-semibold leading-tight text-white" : "mt-6 text-base font-semibold text-white";
      blocks.push(<h4 className={className} key={`heading-${lineIndex}`}>{renderInlineMarkdown(heading[2])}</h4>);
      lineIndex += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) {
      blocks.push(<div className="my-7 h-px bg-white/12" key={`rule-${lineIndex}`} />);
      lineIndex += 1;
      continue;
    }

    const unordered = line.match(/^[-*+]\s+(.+)$/);
    if (unordered) {
      const items: string[] = [];
      while (lineIndex < lines.length) {
        const item = lines[lineIndex].trim().match(/^[-*+]\s+(.+)$/);
        if (!item) break;
        items.push(item[1]);
        lineIndex += 1;
      }
      blocks.push(<ul className="my-4 grid gap-2 pl-5 text-[0.96rem] leading-7 text-white/85 marker:text-[#B99DFF]" key={`list-${lineIndex}`}>{items.map((item, index) => <li key={index}>{renderInlineMarkdown(item)}</li>)}</ul>);
      continue;
    }

    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (ordered) {
      const items: string[] = [];
      while (lineIndex < lines.length) {
        const item = lines[lineIndex].trim().match(/^\d+[.)]\s+(.+)$/);
        if (!item) break;
        items.push(item[1]);
        lineIndex += 1;
      }
      blocks.push(<ol className="my-4 grid gap-2 pl-5 text-[0.96rem] leading-7 text-white/85 marker:font-semibold marker:text-[#B99DFF]" key={`ordered-${lineIndex}`}>{items.map((item, index) => <li key={index}>{renderInlineMarkdown(item)}</li>)}</ol>);
      continue;
    }

    const safetyWarning = line.match(/^>\s*(?:⚠️\s*)?安全提示[:：]\s*(.*)$/);
    if (safetyWarning) {
      blocks.push(<div className="my-4 flex items-start gap-3 rounded-2xl border border-red-400/30 bg-red-400/15 px-4 py-3 text-[0.95rem] leading-7 text-red-50" key={`safety-${lineIndex}`}><span className="mt-0.5 shrink-0 text-base">⚠️</span><span>{renderInlineMarkdown(safetyWarning[1])}</span></div>);
      lineIndex += 1;
      continue;
    }

    if (line.startsWith(">")) {
      blocks.push(<blockquote className="my-5 rounded-r-xl bg-white/[0.07] px-4 py-3 text-[0.96rem] leading-7 text-white/85" key={`quote-${lineIndex}`}>{renderInlineMarkdown(line.replace(/^>\s?/, ""))}</blockquote>);
      lineIndex += 1;
      continue;
    }

    blocks.push(<p className="my-4 text-[0.96rem] leading-8 text-white/85" key={`paragraph-${lineIndex}`}>{renderInlineMarkdown(line)}</p>);
    lineIndex += 1;
  }

  return <article className="mx-auto max-w-[76ch]">{blocks.length ? blocks : <p className="text-white/70">该资源没有返回正文。</p>}</article>;
}

function auditVerdictLabel(verdict?: string) {
  if (verdict === "approved" || verdict === "pass") return "审核通过";
  if (verdict === "needs_revision" || verdict === "revise") return "建议修订";
  return verdict || "未返回";
}

function LegacyLearningTools({ resource, topic, onApplyRevision }: { resource: GeneratedResource; topic: string; onApplyRevision: (resourceType: string, response: LearnerQuestionResponse) => void }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<LearnerQuestionResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [questionError, setQuestionError] = useState<string | null>(null);
  const [revisionApplied, setRevisionApplied] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);
  const [quizResult, setQuizResult] = useState<QuizSubmissionResult | null>(null);
  const [submittingQuiz, setSubmittingQuiz] = useState(false);
  const [quizError, setQuizError] = useState<string | null>(null);
  const quiz = isQuizResource(resource) ? quizFromResource(resource, topic) : null;
  const correctCount = quizResult?.correct_count ?? 0;

  const submitQuestion = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    setQuestionError(null);
    try {
      setAnswer(await askStudyQuestion(question.trim(), topic, resource.content ?? ""));
      setRevisionApplied(false);
    } catch (error) {
      setAnswer(null);
      setQuestionError(error instanceof Error ? error.message : "Unable to get a learning answer.");
    } finally {
      setAsking(false);
    }
  };

  const submitQuizAnswers = async () => {
    if (!quiz) return;
    setSubmittingQuiz(true);
    setQuizError(null);
    try {
      setQuizResult(await submitQuiz(quiz, answers, topic, resource.title));
      setSubmitted(true);
    } catch (error) {
      setQuizError(error instanceof Error ? error.message : "Unable to submit answers.");
    } finally {
      setSubmittingQuiz(false);
    }
  };

  return (
    <section className="mt-8 grid gap-5 border-t border-white/10 pt-7">
      <div className="rounded-2xl bg-white/[0.07] p-5">
        <p className="text-xs font-semibold tracking-[0.12em] text-white/55">学习中遇到疑问？</p>
        <h5 className="mt-2 text-lg font-semibold text-white">提出问题，生成针对性补充</h5>
        <form className="mt-4 grid gap-3" onSubmit={submitQuestion}>
          <textarea className="min-h-24 resize-y rounded-xl bg-black/20 px-4 py-3 text-sm leading-6 text-white outline-none ring-[#B99DFF] placeholder:text-white/45 focus:ring-2" onChange={(event) => setQuestion(event.target.value)} placeholder="例如：工具坐标系和工件坐标系有什么区别？" value={question} />
          <button className="flex items-center justify-between rounded-full bg-white px-5 py-3 text-sm font-semibold text-[#192837] transition hover:brightness-95 disabled:cursor-wait disabled:opacity-60" disabled={asking} type="submit">{asking ? "正在整理建议..." : "获取学习建议"}<Sparkles size={17} strokeWidth={1.8} /></button>
        </form>
        {questionError ? <p className="mt-3 rounded-xl bg-red-400/15 px-4 py-3 text-sm leading-6 text-red-100">{questionError}</p> : null}
        {answer ? <motion.div className="mt-5 rounded-xl bg-[#0B1D2A] p-4 text-sm leading-7 text-white/85" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <p className="font-semibold text-white">针对你的疑问</p><p className="mt-2">{answer.answer}</p>
          <ul className="mt-4 grid gap-2 text-white/75">{answer.suggestions.map((suggestion) => <li key={suggestion}>- {suggestion}</li>)}</ul>
          <button className="mt-4 rounded-full bg-[#7342E2] px-4 py-2 text-xs font-semibold text-white transition hover:brightness-110" onClick={() => onApplyRevision(resource.resource_type, answer)} type="button">应用这段补充到当前资源</button>
        </motion.div> : null}
      </div>
      {quiz ? <div
        className="rounded-2xl bg-white/[0.07] p-5"
        onClickCapture={(event) => {
          if (!submitted && !submittingQuiz && (event.target as HTMLElement).closest("button")) {
            event.preventDefault();
            event.stopPropagation();
            void submitQuizAnswers();
          }
        }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold tracking-[0.12em] text-white/55">即时练习</p><h5 className="mt-2 text-lg font-semibold text-white">{quiz.title}</h5></div>{submitted ? <span className="rounded-full bg-[#B99DFF]/20 px-3 py-2 text-xs font-semibold text-[#E5DBFF]">得分 {correctCount}/{quiz.questions.length}</span> : null}</div>
        <div className="mt-5 grid gap-5">{quiz.questions.map((item, index) => <fieldset className="rounded-xl bg-black/15 p-4" key={item.id}><legend className="px-1 text-sm font-semibold text-white">{index + 1}. {item.stem}</legend><div className="mt-3 grid gap-2">{item.options.map((option) => <label className={`flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${submitted && option.id === item.answer ? "bg-emerald-400/20 text-white" : submitted && answers[item.id] === option.id ? "bg-red-400/20 text-white" : "bg-white/[0.06] text-white/85 hover:bg-white/10"}`} key={option.id}><input checked={answers[item.id] === option.id} className="accent-[#7342E2]" disabled={submitted} name={item.id} onChange={() => setAnswers((current) => ({ ...current, [item.id]: option.id }))} type="radio" /><span><strong>{option.id}.</strong> {option.text}</span></label>)}</div>{submitted ? <p className="mt-3 text-sm leading-6 text-white/75"><span className="font-semibold text-white">解析：</span>{item.explanation}</p> : null}</fieldset>)}</div>
        {!submitted ? <button className="mt-5 flex w-full items-center justify-between rounded-full bg-[#7342E2] px-5 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50" disabled={Object.keys(answers).length !== quiz.questions.length} onClick={() => setSubmitted(true)} type="button">提交并查看解析<ArrowRightCircle size={17} /></button> : <button className="mt-5 rounded-full bg-white/10 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/20" onClick={() => { setAnswers({}); setSubmitted(false); }} type="button">重新作答</button>}
        {quizError ? <p className="mt-4 rounded-xl bg-red-400/15 px-4 py-3 text-sm text-red-100">{quizError}</p> : null}
        {submitted && quizResult?.learning_advice?.length ? <ul className="mt-4 grid gap-2 rounded-xl bg-[#B99DFF]/10 p-4 text-sm leading-6 text-[#EDE8FF]">{quizResult.learning_advice.map((advice) => <li key={advice}>- {decodeEscapedText(advice)}</li>)}</ul> : null}
      </div> : null}
      {quiz && resource.supplements?.length ? <section className="rounded-2xl border border-[#B99DFF]/30 bg-[#B99DFF]/10 p-5">
        <p className="text-xs font-semibold tracking-[0.12em] text-[#E5DBFF]">针对疑问的补充资源</p>
        <div className="mt-4 grid gap-5">{resource.supplements.map((supplement, index) => <article className="rounded-xl bg-[#0B1D2A]/80 p-4" key={`${supplement.title}-${index}`}>
          <h5 className="text-base font-semibold text-white">{supplement.title}</h5>
          <div className="mt-3"><ResourceMarkdown content={supplement.content} /></div>
        </article>)}</div>
      </section> : null}
    </section>
  );
}

function LearningTools({ resource, topic, onApplyRevision, onResolveQuiz, onGenerateAdaptiveQuiz, quizAttempt, onQuizAttemptChange }: {
  resource: GeneratedResource;
  topic: string;
  onApplyRevision: (resourceType: string, response: LearnerQuestionResponse) => void;
  onResolveQuiz: (resourceId: string | undefined, quiz: Quiz) => void;
  onGenerateAdaptiveQuiz: (result: QuizSubmissionResult) => Promise<void>;
  quizAttempt?: QuizAttempt;
  onQuizAttemptChange: (resource: GeneratedResource, update: (current: QuizAttempt) => QuizAttempt) => void;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<LearnerQuestionResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [questionError, setQuestionError] = useState<string | null>(null);
  const [revisionApplied, setRevisionApplied] = useState(false);
  const [submittingQuiz, setSubmittingQuiz] = useState(false);
  const [generatingAdaptiveQuiz, setGeneratingAdaptiveQuiz] = useState(false);
  const attempt = quizAttempt ?? createQuizAttempt();
  const answers = attempt.answers;
  const submitted = attempt.submitted;
  const quizResult = attempt.quizResult;
  const quizError = attempt.quizError;
  const resolvedQuiz = attempt.resolvedQuiz;
  const updateQuizAttempt = (update: (current: QuizAttempt) => QuizAttempt) => onQuizAttemptChange(resource, update);
  const setAnswers = (next: Record<string, string> | ((current: Record<string, string>) => Record<string, string>)) => {
    updateQuizAttempt((current) => ({
      ...current,
      answers: typeof next === "function" ? next(current.answers) : next,
    }));
  };
  const setSubmitted = (next: boolean) => updateQuizAttempt((current) => ({ ...current, submitted: next }));
  const setQuizResult = (next: QuizSubmissionResult | null) => updateQuizAttempt((current) => ({
    ...current,
    quizResult: next ? decodeApiText(next) : null,
  }));
  const setQuizError = (next: string | null) => updateQuizAttempt((current) => ({ ...current, quizError: next }));
  const setResolvedQuiz = (next: Quiz | null) => updateQuizAttempt((current) => ({ ...current, resolvedQuiz: next }));
  const quizNeedsReview = resource.quiz_validation_status === "needs_review";
  const parsedQuiz = isQuizResource(resource) ? quizFromResource(resource, topic) : null;
  const quiz = resolvedQuiz ?? parsedQuiz;
  const invalidQuizResource = isQuizResource(resource) && !quiz;
  const quizValidationError = resource.quiz_validation_error ? decodeEscapedText(resource.quiz_validation_error) : null;
  const allQuestionsAnswered = Boolean(quiz?.questions.every((item) => answers[item.id]?.trim()));
  const quizHasAnswerKey = Boolean(quiz?.questions.length && quiz.questions.every((item) => item.answer.trim() && item.explanation.trim()));
  const quizSupplements = quiz ? getResourceSupplements(resource) : [];
  const detailByQuestion = new Map(quizResult?.details.map((detail) => [detail.question_id, detail]));

  const submitQuestion = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) return;

    setAsking(true);
    setQuestionError(null);
    try {
      setAnswer(await askStudyQuestion(trimmedQuestion, topic, resource.content ?? ""));
      setRevisionApplied(false);
    } catch (error) {
      setAnswer(null);
      setQuestionError(error instanceof Error ? error.message : "暂时无法获取回答，请确认本地 API 已启动后重试。");
    } finally {
      setAsking(false);
    }
  };

  const submitQuizAnswers = async () => {
    if (!quiz || !allQuestionsAnswered) return;
    if (!quizHasAnswerKey) {
      setSubmittingQuiz(true);
      setQuizError(null);
      try {
        const quizForSubmission = await resolveQuizAnswerKey(quiz, topic, resource.content ?? "");
        setResolvedQuiz(quizForSubmission);
        onResolveQuiz(resource.resource_id, quizForSubmission);
        setQuizResult(await submitQuiz(quizForSubmission, answers, topic, resource.title));
        setSubmitted(true);
      } catch (error) {
        setQuizError("当前资源没有可独立验证的标准答案和解析，系统不会猜测答案。请重新生成测试题。");
      } finally {
        setSubmittingQuiz(false);
      }
      return;
    }
    if (!quizHasAnswerKey) {
      setQuizError("这套测试题缺少标准答案或解析，无法可靠评分。请重新生成资源后再提交。");
      return;
    }
    setSubmittingQuiz(true);
    setQuizError(null);
    try {
      setQuizResult(await submitQuiz(quiz, answers, topic, resource.title));
      setSubmitted(true);
    } catch (error) {
      setQuizError(error instanceof Error ? error.message : "提交失败，请确认本地 API 已启动后重试。");
    } finally {
      setSubmittingQuiz(false);
    }
  };

  const generateAdaptiveQuiz = async () => {
    if (!quizResult || generatingAdaptiveQuiz) return;
    setGeneratingAdaptiveQuiz(true);
    setQuizError(null);
    try {
      await onGenerateAdaptiveQuiz(quizResult);
    } catch (error) {
      setQuizError(error instanceof Error ? error.message : "Unable to generate the next quiz round.");
    } finally {
      setGeneratingAdaptiveQuiz(false);
    }
  };

  return (
    <section className="mt-8 grid gap-5 border-t border-white/10 pt-7">
      <div className="rounded-2xl bg-white/[0.07] p-5">
        <p className="text-xs font-semibold tracking-[0.12em] text-white/55">学习中遇到疑问？</p>
        <h5 className="mt-2 text-lg font-semibold text-white">提出问题，获得直接解答</h5>
        <form className="mt-4 grid gap-3" onSubmit={submitQuestion}>
          <textarea className="min-h-24 resize-y rounded-xl bg-black/20 px-4 py-3 text-sm leading-6 text-white outline-none ring-[#B99DFF] placeholder:text-white/45 focus:ring-2" onChange={(event) => setQuestion(event.target.value)} placeholder="例如：什么是手动限速模式？出现送丝异常时应检查哪些地方？" value={question} />
          <button className="flex items-center justify-between rounded-full bg-white px-5 py-3 text-sm font-semibold text-[#192837] transition hover:brightness-95 disabled:cursor-wait disabled:opacity-60" disabled={asking} type="submit">{asking ? "正在获取回答..." : "获取学习建议"}<Sparkles size={17} strokeWidth={1.8} /></button>
        </form>
        {questionError ? <p className="mt-3 rounded-xl bg-red-400/15 px-4 py-3 text-sm leading-6 text-red-100">{questionError}</p> : null}
        {answer ? <motion.div className="mt-5 rounded-xl bg-[#0B1D2A] p-4 text-sm leading-7 text-white/85" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <p className="font-semibold text-white">针对你的问题</p>
          <p className="mt-2 whitespace-pre-wrap">{answer.answer}</p>
          {answer.suggestions.length ? <ul className="mt-4 grid gap-2 border-t border-white/10 pt-4 text-white/75">{answer.suggestions.map((suggestion) => <li key={suggestion}>- {suggestion}</li>)}</ul> : null}
          <button className="mt-4 rounded-full bg-[#7342E2] px-4 py-2 text-xs font-semibold text-white transition hover:brightness-110 disabled:opacity-60" disabled={revisionApplied} onClick={() => { onApplyRevision(resource.resource_type, answer); setRevisionApplied(true); }} type="button">{revisionApplied ? "补充已加入当前资源" : "将补充内容加入当前资源"}</button>
        </motion.div> : null}
      </div>
      {quizNeedsReview && quiz ? <section className="rounded-2xl border border-amber-300/30 bg-amber-300/10 p-5 text-amber-50">
        <p className="text-xs font-semibold tracking-[0.12em] text-amber-100/70">题目修复中</p>
        <h5 className="mt-2 text-lg font-semibold">可评分题目已可作答</h5>
        <p className="mt-2 text-sm leading-6 text-amber-50/85">个别不完整题目正在单独替换；当前显示的题目均已包含标准答案和解析，可以直接完成并提交。</p>
      </section> : null}
      {invalidQuizResource && quizValidationError ? <section className="rounded-2xl border border-amber-300/30 bg-amber-300/10 p-5 text-amber-50">
        <p className="text-xs font-semibold tracking-[0.12em] text-amber-100/70">{decodeEscapedText("\u6d4b\u8bd5\u9898\u5f85\u6838\u9a8c")}</p>
        <h5 className="mt-2 text-lg font-semibold">{decodeEscapedText("\u9898\u76ee\u5df2\u4fdd\u7559\uff0c\u6682\u4e0d\u652f\u6301\u81ea\u52a8\u8bc4\u5206")}</h5>
        <p className="mt-2 text-sm leading-6 text-amber-50/85">{`\u6821\u9a8c\u63d0\u793a\uff1a${quizValidationError}`}</p>
      </section> : null}
      {invalidQuizResource && !quizValidationError ? <section className="rounded-2xl border border-amber-300/30 bg-amber-300/10 p-5 text-amber-50">
        <p className="text-xs font-semibold tracking-[0.12em] text-amber-100/70">测试题需要重新生成</p>
        <h5 className="mt-2 text-lg font-semibold">当前内容不是可判定的测试题</h5>
        <p className="mt-2 text-sm leading-6 text-amber-50/85">题干不完整，或每题缺少可验证的标准答案与解析。系统不会把章节标题当作题目，也不会猜测答案。请重新生成测试题后再作答。</p>
      </section> : null}
      {quiz ? <div className="rounded-2xl bg-white/[0.07] p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><p className="text-xs font-semibold tracking-[0.12em] text-white/55">测试题</p><h5 className="mt-2 text-lg font-semibold text-white">{quiz.title}</h5></div>
          {submitted && quizResult ? <span className="rounded-full bg-[#B99DFF]/20 px-3 py-2 text-xs font-semibold text-[#E5DBFF]">得分 {quizResult.correct_count}/{quizResult.total}</span> : null}
        </div>
        <p className="mt-3 text-sm leading-6 text-white/65">请先完成每一题。提交前不会显示标准答案和解析；选择题请输入选项字母，简答题请直接输入答案。</p>
        <div className="mt-5 grid gap-5">{quiz.questions.map((item, index) => {
          const detail = detailByQuestion.get(item.id);
          const isChoiceQuestion = item.questionType === "choice" && hasCompleteChoiceOptions(item.options);
          return <article className="rounded-xl bg-black/15 p-4" key={item.id}>
            <h6 className="text-sm font-semibold leading-6 text-white">{index + 1}. {item.stem}</h6>
            {isChoiceQuestion ? <div className="mt-4 grid gap-2" role="group">{item.options.map((option) => {
              const selected = answers[item.id] === option.id;
              return <button aria-pressed={selected} className={`flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left text-sm leading-6 transition ${selected ? "border-[#B99DFF] bg-[#7342E2]/30 text-white" : "border-transparent bg-white/[0.06] text-white/80 hover:border-white/25 hover:bg-white/[0.1]"}`} disabled={submitted} key={option.id} onClick={() => setAnswers((current) => ({ ...current, [item.id]: option.id }))} type="button"><span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-semibold ${selected ? "bg-white text-[#7342E2]" : "bg-white/10 text-white/80"}`}>{option.id}</span><span className="pt-0.5">{option.text}</span></button>;
            })}</div> : null}
            {!isChoiceQuestion ? <>
            <label className="mt-4 grid gap-2 text-xs font-semibold text-white/65">你的答案<textarea className="min-h-20 resize-y rounded-lg bg-white/[0.08] px-3 py-2 text-sm font-normal leading-6 text-white outline-none ring-[#B99DFF] focus:ring-2 disabled:opacity-70" disabled={submitted} onChange={(event) => setAnswers((current) => ({ ...current, [item.id]: event.target.value }))} placeholder={item.options.length ? "请输入选项字母，例如 B" : "请写下你的答案"} value={answers[item.id] || ""} /></label>
            </> : null}
            {submitted && detail ? <div className={`mt-4 rounded-lg p-3 text-sm leading-6 ${detail.correct ? "bg-emerald-400/15 text-emerald-50" : "bg-red-400/15 text-red-50"}`}><p className="font-semibold">{detail.correct ? "回答正确" : "需要复习"}</p><p className="mt-1">标准答案：{decodeEscapedText(detail.standard_answer)}</p><p className="mt-1">解析：{decodeEscapedText(detail.explanation)}</p></div> : null}
          </article>;
        })}</div>
        {!submitted ? <button className="mt-5 flex w-full items-center justify-between rounded-full bg-[#7342E2] px-5 py-3 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50" disabled={!allQuestionsAnswered || submittingQuiz} onClick={() => void submitQuizAnswers()} type="button">{submittingQuiz ? "正在提交评分..." : "提交并查看答案解析"}<ArrowRightCircle size={17} /></button> : <button className="mt-5 rounded-full bg-white/10 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/20" onClick={() => { setAnswers({}); setSubmitted(false); setQuizResult(null); setQuizError(null); }} type="button">重新作答</button>}
        {quizError ? <p className="mt-4 rounded-xl bg-red-400/15 px-4 py-3 text-sm text-red-100">{quizError}</p> : null}
        {submitted && quizResult?.learning_advice?.length ? <ul className="mt-4 grid gap-2 rounded-xl bg-[#B99DFF]/10 p-4 text-sm leading-6 text-[#EDE8FF]">{quizResult.learning_advice.map((advice) => <li key={advice}>- {decodeEscapedText(advice)}</li>)}</ul> : null}
        {submitted && quizResult ? <section className="mt-5 rounded-xl border border-[#B99DFF]/35 bg-[#B99DFF]/10 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold text-[#E5DBFF]">{decodeEscapedText("\u5b66\u4e60\u753b\u50cf\u5df2\u66f4\u65b0")}</p><h6 className="mt-1 text-base font-semibold text-white">{decodeEscapedText("\u672c\u8f6e\u8868\u73b0\u5df2\u7528\u4e8e\u4e0b\u4e00\u8f6e\u51fa\u9898")}</h6></div><span className="rounded-full bg-white/10 px-3 py-1.5 text-xs font-semibold text-white">{quizResult.score}%</span></div>
          {quizResult.feedback?.weak_topics?.length ? <p className="mt-3 text-sm leading-6 text-white/80">{decodeEscapedText("\u4f18\u5148\u8865\u5f3a\uff1a")}{quizResult.feedback.weak_topics.map((item) => `${decodeEscapedText(item.topic)} ${Math.round(item.mastery)}%`).join("\u3001")}</p> : null}
          {quizResult.feedback?.strong_topics?.length ? <p className="mt-2 text-sm leading-6 text-white/70">{decodeEscapedText("\u5df2\u638c\u63e1\uff1a")}{quizResult.feedback.strong_topics.map((item) => `${decodeEscapedText(item.topic)} ${Math.round(item.mastery)}%`).join("\u3001")}</p> : null}
          {quizResult.feedback?.recommendations?.length ? <p className="mt-2 text-sm leading-6 text-white/70">{decodeEscapedText(quizResult.feedback.recommendations[0])}</p> : null}
          <button className="mt-4 flex w-full items-center justify-between rounded-full bg-white px-4 py-3 text-sm font-semibold text-[#192837] transition hover:bg-[#E5DBFF] disabled:cursor-wait disabled:opacity-60" disabled={generatingAdaptiveQuiz} onClick={() => void generateAdaptiveQuiz()} type="button">{generatingAdaptiveQuiz ? "\u6b63\u5728\u6839\u636e\u65b0\u753b\u50cf\u51fa\u9898..." : "\u751f\u6210\u4e0b\u4e00\u8f6e\u9488\u5bf9\u6027\u6d4b\u8bd5"}<ArrowRightCircle size={17} /></button>
        </section> : null}
      </div> : null}
      {quizSupplements.length ? <section className="rounded-2xl border border-[#B99DFF]/30 bg-[#B99DFF]/10 p-5">
        <p className="text-xs font-semibold tracking-[0.12em] text-[#E5DBFF]">针对疑问的补充资源</p>
        <div className="mt-4 grid gap-5">{quizSupplements.map((supplement, index) => <article className="rounded-xl bg-[#0B1D2A]/80 p-4" key={`${supplement.title}-${index}`}>
          <h5 className="text-base font-semibold text-white">{supplement.title}</h5>
          <div className="mt-3"><ResourceMarkdown content={supplement.content} /></div>
        </article>)}</div>
      </section> : null}
    </section>
  );
}

function WorkflowProgress({ events, mode }: { events: WorkflowEvent[]; mode: "idle" | "waiting" | "connected" | "demo" | "complete" }) {
  const modeLabel = mode === "connected" ? "实时连接中" : mode === "demo" ? "演示流程" : mode === "waiting" ? "等待任务响应" : mode === "complete" ? "任务已完成" : "尚未开始";
  return (
    <section className="rounded-2xl bg-[#0B1D2A] p-5 text-white" aria-label="Agent 实时工作状态">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold tracking-[0.12em] text-white/55">Agent 工作状态</p><h5 className="mt-2 text-lg font-semibold">协同工作流</h5></div><span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/75">{modeLabel}</span></div>
      <ol className="mt-5 grid gap-2">{workflowStages.map((stage, index) => { const event = events.find((item) => item.agent === stage.agent); const status = event?.status || "pending"; const color = status === "done" ? "bg-emerald-400" : status === "running" ? "bg-[#B99DFF] animate-pulse" : status === "error" ? "bg-red-400" : "bg-white/25"; const label = status === "done" ? "已完成" : status === "running" ? "进行中" : status === "error" ? "异常" : "等待中"; return <li className="flex items-center gap-3 rounded-xl bg-white/[0.06] px-3 py-3 text-sm" key={stage.agent}><span className={`h-2.5 w-2.5 shrink-0 rounded-full ${color}`} /><span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-white/10 text-[11px]">0{index + 1}</span><span className="shrink-0 font-semibold">{stage.label}</span><span className="min-w-0 flex-1 text-right text-xs leading-5 text-white/60">{event?.message || label}</span></li>; })}</ol>
    </section>
  );
}

function GenerationProgressScreen({ events, mode }: { events: WorkflowEvent[]; mode: "idle" | "waiting" | "connected" | "demo" | "complete" }) {
  const reducedMotion = useReducedMotion();
  return (
    <>
      <motion.div className="fixed inset-0 z-[80] bg-[#192837]/35 backdrop-blur-[5px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
      <motion.section
        aria-live="polite"
        aria-label="生成进度"
        className="fixed inset-x-3 bottom-3 top-3 z-[90] mx-auto flex max-w-[760px] flex-col overflow-y-auto rounded-[2rem] bg-[#F2F2EE]/95 p-6 text-[#192837] shadow-[0_28px_100px_rgba(25,40,55,0.34)] backdrop-blur-xl sm:inset-x-auto sm:bottom-auto sm:right-8 sm:top-1/2 sm:max-h-[calc(100dvh-48px)] sm:w-[min(720px,calc(100vw-64px))] sm:-translate-y-1/2 sm:p-8"
        initial={reducedMotion ? false : { opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.08, duration: 0.48, ease }}
      >
        <p className="text-xs font-semibold tracking-[0.16em] text-[#192837]/55">XH-AGENT</p>
        <h2 className="mt-3 font-[var(--font-heading)] text-3xl leading-tight sm:text-4xl">正在构建你的学习方案</h2>
        <p className="mt-4 max-w-[60ch] text-sm leading-7 text-[#192837]/72">系统会依次完成学习画像诊断、知识检索、资源生成、内容审核与保真修正。完成后将自动进入学习工作台。</p>
        <div className="mt-8"><WorkflowProgress events={events} mode={mode} /></div>
      </motion.section>
    </>
  );
}

function BrandMark() {
  return (
    <svg aria-label="XH Agent" className="h-8 w-8 shrink-0" fill="none" overflow="visible" viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg">
      <path d="M 64 128 L 64.5 128 L 32 95 L 0 64 L 0 0 L 64 0 L 128 64 L 128 64.5 L 161 32 L 192 0 L 256 0 L 256 64 L 192 128 L 128 128 L 128 192 L 96 223 L 63.5 256 L 0 256 L 0 192 Z M 256 192 L 224 223 L 191.5 256 L 128 256 L 128 192 L 192 128 L 256 128 Z" fill="#192837" />
    </svg>
  );
}

function ActionButton({ children, kind, onClick }: { children: ReactNode; kind: "accent" | "quiet"; onClick?: () => void }) {
  const isAccent = kind === "accent";
  return (
    <motion.button
      className={isAccent ? "rounded-full bg-[#7342E2] px-5 py-2.5 text-sm font-semibold text-white shadow-[0_4px_24px_rgba(115,66,226,0.28)]" : "rounded-full bg-[#F2F2EE] px-5 py-2.5 text-sm font-semibold text-[#192837]"}
      onClick={onClick}
      type="button"
      whileHover={{ scale: 1.04, filter: isAccent ? "brightness(1.1)" : "brightness(0.98)" }}
      whileTap={{ scale: 0.96 }}
    >
      {children}
    </motion.button>
  );
}

function ExpandedWorkspaceLayout({
  generationResult,
  topic,
  selectedResource,
  setSelectedResource,
  activeStep,
  setActiveStep,
  selectedQualityGate,
  setSelectedQualityGate,
  onOpenWorkflow,
  onOpenQualityGate,
  onApplyRevision,
  onResolveQuiz,
  onGenerateAdaptiveQuiz,
  quizAttempts,
  onQuizAttemptChange,
  onExport,
  backendDemoMode,
}: {
  generationResult: GenerationResult | null;
  topic: string;
  selectedResource: string | null;
  setSelectedResource: (value: string) => void;
  activeStep: number | null;
  setActiveStep: (value: number | null) => void;
  selectedQualityGate: QualityGate | null;
  setSelectedQualityGate: (value: QualityGate | null) => void;
  onOpenWorkflow: (index: number) => void;
  onOpenQualityGate: (id: QualityGate) => void;
  onApplyRevision: (resourceType: string, response: LearnerQuestionResponse) => void;
  onResolveQuiz: (resourceId: string | undefined, quiz: Quiz) => void;
  onGenerateAdaptiveQuiz: (result: QuizSubmissionResult) => Promise<void>;
  quizAttempts: Record<string, QuizAttempt>;
  onQuizAttemptChange: (resource: GeneratedResource, update: (current: QuizAttempt) => QuizAttempt) => void;
  onExport: () => void;
  backendDemoMode: boolean | null;
}) {
  const resources = generationResult?.resources ?? [];
  const resource = resources.find((item) => item.resource_type === selectedResource);
  const resourceIndex = resources.findIndex((item) => item.resource_type === selectedResource);
  const audit = generationResult?.audit?.find((item) => item.resource_type === selectedResource || item.resource_index === resourceIndex);
  const quizRounds = resource && isQuizResource(resource) ? resources.filter(isQuizResource) : [];
  const workflowDetail = "详情已在弹窗中打开。";
  return (
    <div className="workspace-expanded-content mt-8 grid min-h-[calc(100dvh-150px)] min-w-0 w-full max-w-none grid-cols-[230px_minmax(0,1fr)] gap-8 rounded-[2rem] bg-[#192837] p-5 text-white shadow-[0_24px_70px_rgba(25,40,55,0.2)] sm:p-7 lg:grid-cols-[260px_minmax(0,1fr)] lg:gap-10">
      <nav aria-label="学习工作台目录" className="self-start lg:sticky lg:top-7">
        <div className="rounded-2xl bg-white/[0.07] p-4">
          <p className="text-xs font-semibold tracking-[0.14em] text-white/55">资源目录</p>
          <div className="mt-4 grid gap-2">
            {workspaceResourceItems(resources).map((item, index) => <button aria-current={selectedResource === item.resource_type ? "page" : undefined} className={`flex items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-semibold transition ${selectedResource === item.resource_type ? "bg-[#7342E2] text-white shadow-[0_8px_20px_rgba(115,66,226,0.28)]" : "bg-white/[0.06] text-white/75 hover:bg-white/12 hover:text-white"}`} key={item.resource_type} onClick={() => setSelectedResource(item.resource_type)} type="button"><span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-white/15 text-[11px]">0{index + 1}</span><span className="truncate">{resourceLabel(item.resource_type)}</span></button>)}
            {!generationResult?.resources?.length ? <p className="px-3 py-2 text-sm leading-6 text-white/55">生成资源后显示目录</p> : null}
          </div>
          {generationResult?.resources?.length ? (
            <button
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-white/[0.1] px-3 py-3 text-sm font-semibold text-white transition hover:bg-[#7342E2] hover:shadow-[0_8px_20px_rgba(115,66,226,0.28)]"
              onClick={onExport}
              type="button"
            >
              <Download size={16} strokeWidth={1.8} />
              导出全部资源
            </button>
          ) : null}
        </div>
        <div className="mt-4 rounded-2xl bg-white/[0.07] p-4">
          <p className="text-xs font-semibold tracking-[0.14em] text-white/55">协同工作流</p>
          <div className="mt-4 grid gap-2">
            {workflowSteps.map((step, index) => <button aria-current={activeStep === index ? "step" : undefined} className={`flex items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-semibold transition ${activeStep === index ? "bg-white text-[#192837]" : "text-white/75 hover:bg-white/[0.08] hover:text-white"}`} key={step} onClick={() => { setActiveStep(index); onOpenWorkflow(index); }} type="button"><span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] ${activeStep === index ? "bg-[#7342E2] text-white" : "bg-white/12"}`}>0{index + 1}</span><span>{step}</span></button>)}
          </div>
        </div>
        <div className="mt-4 rounded-2xl bg-white/[0.07] p-4">
          <p className="text-xs font-semibold tracking-[0.14em] text-white/55">质量闸门</p>
          <div className="mt-4 grid gap-2">
            {qualityGates.map((gate) => <button aria-pressed={selectedQualityGate === gate.id} className={`rounded-xl px-3 py-3 text-left text-sm font-semibold transition ${selectedQualityGate === gate.id ? "bg-white text-[#192837]" : "text-white/75 hover:bg-white/[0.08] hover:text-white"}`} key={gate.id} onClick={() => { setSelectedQualityGate(gate.id); onOpenQualityGate(gate.id); }} type="button">{gate.label}</button>)}
          </div>
        </div>
      </nav>

      <main className="min-w-0 w-full">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><p className="text-xs font-semibold tracking-[0.14em] text-white/55">本次生成结果</p><h3 className="mt-2 text-2xl font-semibold leading-tight">{topic || "学习资源工作台"}</h3></div>
          <span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/85">{generationResult?.mode === "demo" || backendDemoMode === true ? "本地演示" : "DeepSeek Chat"}</span>
        </div>
        {generationResult?.diagnosis?.summary ? <p className="mt-5 max-w-[78ch] text-base leading-8 text-white/80">诊断：{generationResult.diagnosis.summary}</p> : null}

        {resource ? <motion.article className="mt-7 rounded-2xl bg-[#102333] p-6 shadow-inner shadow-black/10 sm:p-8 lg:p-10" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} key={selectedResource}>
          <header className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold text-white/55">{isQuizResource(resource) ? `\u7b2c ${quizRoundNumber(resources, resource)} \u8f6e\u6d4b\u8bd5` : "资源预览"}</p><h4 className="mt-2 text-2xl font-semibold leading-tight text-white">{resource.title}</h4></div>{resource.estimated_duration_minutes ? <span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/75">预计 {resource.estimated_duration_minutes} 分钟</span> : null}</header>
          <RiskBanner level={resource.risk_level} />
          {resource.robot_metadata ? <div className="mt-4 rounded-xl bg-white/[0.07] px-4 py-3 text-xs leading-6 text-white/70"><span className="font-semibold text-white/85">适配信息</span>　适配品牌：{resource.robot_metadata.brand || "未标注"} | 控制器版本：{resource.robot_metadata.controller_version || "未标注"} | 适用机型：{resource.robot_metadata.applicable_model || "未标注"}</div> : null}
          <LookupChips instruction_links={resource.instruction_links} alarm_links={resource.alarm_links} />
          <References citations={resource.citations} />
          {resource.key_takeaways?.length ? <aside className="mt-7 rounded-xl bg-white/[0.07] p-5"><p className="text-xs font-semibold text-white/60">学习重点</p><ul className="mt-3 grid gap-2 pl-5 text-sm leading-7 text-white/85 marker:text-[#B99DFF]">{resource.key_takeaways.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></aside> : null}
                {isQuizResource(resource) ? (
                  <div className="mt-8 rounded-xl bg-white/[0.06] p-5 text-sm leading-7 text-white/75">
                    <p className="font-semibold text-white">答题说明</p>
                    <p className="mt-2">请完成每一道题后提交。提交前不会显示标准答案或解析。</p>
                  </div>
                ) : (
                  <div className="mt-8"><ResourceMarkdown content={resource.content || ""} /></div>
                )}
          <LearningTools
            onApplyRevision={onApplyRevision}
            onGenerateAdaptiveQuiz={onGenerateAdaptiveQuiz}
            onQuizAttemptChange={onQuizAttemptChange}
            onResolveQuiz={onResolveQuiz}
            quizAttempt={quizAttempts[quizAttemptKey(resource)]}
            resource={resource}
            topic={topic}
          />
          {isQuizResource(resource) ? quizRounds.slice(1).map((roundResource) => {
            const roundResourceIndex = resources.indexOf(roundResource);
            const roundAudit = generationResult?.audit?.find((item) => item.resource_type === roundResource.resource_type || item.resource_index === roundResourceIndex);
            const roundNumber = quizRoundNumber(resources, roundResource);
            return <section className="mt-10 border-t border-white/10 pt-8" key={roundResource.resource_id ?? roundResource.resource_type}>
              <header className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold text-white/55">{`\u7b2c ${roundNumber} \u8f6e\u6d4b\u8bd5`}</p><h5 className="mt-2 text-xl font-semibold leading-tight text-white">{roundResource.title}</h5></div>{roundResource.estimated_duration_minutes ? <span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/75">预计 {roundResource.estimated_duration_minutes} 分钟</span> : null}</header>
              {roundResource.key_takeaways?.length ? <aside className="mt-6 rounded-xl bg-white/[0.07] p-5"><p className="text-xs font-semibold text-white/60">学习重点</p><ul className="mt-3 grid gap-2 pl-5 text-sm leading-7 text-white/85 marker:text-[#B99DFF]">{roundResource.key_takeaways.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></aside> : null}
              <div className="mt-6 rounded-xl bg-white/[0.06] p-5 text-sm leading-7 text-white/75"><p className="font-semibold text-white">答题说明</p><p className="mt-2">请完成每一道题后提交。提交前不会显示标准答案或解析。</p></div>
              <LearningTools
                onApplyRevision={onApplyRevision}
                onGenerateAdaptiveQuiz={onGenerateAdaptiveQuiz}
                onQuizAttemptChange={onQuizAttemptChange}
                onResolveQuiz={onResolveQuiz}
                quizAttempt={quizAttempts[quizAttemptKey(roundResource)]}
                resource={roundResource}
                topic={topic}
              />
              <footer className="mt-8 rounded-xl bg-white/[0.07] px-5 py-4 text-sm leading-7 text-white/75"><span className="font-semibold text-white">审核状态：</span>{auditVerdictLabel(roundAudit?.verdict)}{roundAudit?.issues?.[0]?.detail ? <span className="ml-2">{roundAudit.issues[0].detail}</span> : null}</footer>
            </section>;
          }) : null}
          {isHandsOnResourceType(resource.resource_type) ? <p className="mt-7 text-xs leading-6 text-white/45">本内容仅作教学参考，实际操作请遵守现场安全管理规范与设备官方手册。</p> : null}
          <footer className="mt-9 rounded-xl bg-white/[0.07] px-5 py-4 text-sm leading-7 text-white/75"><span className="font-semibold text-white">审核状态：</span>{auditVerdictLabel(audit?.verdict)}{audit?.issues?.[0]?.detail ? <span className="ml-2">{audit.issues[0].detail}</span> : null}</footer>
        </motion.article> : <div className="mt-7 rounded-2xl bg-[#102333] p-8 text-white/65">选择左侧资源目录查看内容。</div>}

        {activeStep !== null ? <motion.section className="mt-6 rounded-2xl bg-white/[0.08] p-6" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} key={`workflow-${activeStep}`}><p className="text-xs font-semibold tracking-[0.14em] text-white/55">工作流详情</p><h4 className="mt-2 text-xl font-semibold text-white">{workflowSteps[activeStep]}</h4><p className="mt-3 text-sm leading-7 text-white/75">{workflowDetail}</p></motion.section> : null}
        <motion.section className="mt-6 rounded-2xl bg-white/[0.08] p-6" layout><p className="text-xs font-semibold tracking-[0.14em] text-white/55">质量闸门详情</p><h4 className="mt-2 text-xl font-semibold text-white">{qualityGates.find((gate) => gate.id === selectedQualityGate)?.label}</h4><p className="mt-3 text-sm leading-7 text-white/75">{selectedQualityGate === "evidence" ? "查看每种资源是否有知识库依据和审核结论。" : selectedQualityGate === "difficulty" ? `建议难度：${generationResult?.diagnosis?.recommended_difficulty || "等待学情诊断"}` : "查看资源的表达质量、结构完整性和可用性。"}</p></motion.section>
      </main>
    </div>
  );
}

function MobileMenu({ open, onClose, onNavigate, onOpenGenerator, onOpenWorkspace }: { open: boolean; onClose: () => void; onNavigate: (index: number) => void; onOpenGenerator: () => void; onOpenWorkspace: () => void }) {
  const reducedMotion = useReducedMotion();
  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.button aria-label="关闭菜单遮罩" className="fixed inset-0 z-40 cursor-default bg-[rgba(25,40,55,0.35)] backdrop-blur-[4px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.aside aria-label="移动端导航" className="fixed right-0 top-0 z-50 flex h-[100dvh] w-[min(88vw,360px)] flex-col bg-[#CFC8C5] p-6 text-[#192837] shadow-[-12px_0_48px_rgba(25,40,55,0.18)]" initial={reducedMotion ? false : { x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ duration: 0.45, ease }}>
            <div className="flex items-center justify-between"><BrandMark /><button aria-label="关闭菜单" className="grid h-10 w-10 place-items-center rounded-full bg-white/55" onClick={onClose}><X size={20} strokeWidth={1.8} /></button></div>
            <div className="mt-6 h-px bg-[#192837]/20" />
            <nav className="mt-9 grid gap-5" aria-label="移动端导航链接">
              {navigation.map((item, index) => <motion.button key={item} className="text-left text-2xl font-medium" type="button" initial={reducedMotion ? false : { opacity: 0, x: 18 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.18 + index * 0.07, duration: 0.35, ease }} onClick={() => { onNavigate(index); onClose(); }}>{item}</motion.button>)}
            </nav>
            <div className="mt-auto grid gap-3"><ActionButton kind="accent" onClick={onOpenGenerator}>生成学习资源</ActionButton><ActionButton kind="quiet" onClick={onOpenWorkspace}>进入工作台</ActionButton></div>
          </motion.aside>
        </>
      ) : null}
    </AnimatePresence>
  );
}

export function VaultShieldHero({ variant }: { variant: Variant }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [activeStep, setActiveStep] = useState<number | null>(null);
  const [activePanel, setActivePanel] = useState<Panel>("overview");
  const [generatorOpen, setGeneratorOpen] = useState(false);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [workspaceExpanded, setWorkspaceExpanded] = useState(false);
  const [selectedQualityGate, setSelectedQualityGate] = useState<QualityGate | null>("evidence");
  const [workspaceDialog, setWorkspaceDialog] = useState<WorkspaceDialog | null>(null);
  const [homeInfoDialog, setHomeInfoDialog] = useState<"workflow" | "overview" | null>(null);
  const [topic, setTopic] = useState("");
  const [resourceTypes, setResourceTypes] = useState<string[]>(["lecture"]);
  const [resourceReady, setResourceReady] = useState(false);
  const [selectedResource, setSelectedResource] = useState<string | null>(null);
  const [generationResult, setGenerationResult] = useState<GenerationResult | null>(null);
  const [generationSeq, setGenerationSeq] = useState(0);
  const [coreMap, setCoreMap] = useState<CoreMap | null>(null);
  const [quizAttempts, setQuizAttempts] = useState<Record<string, QuizAttempt>>({});
  const [safetyAckResource, setSafetyAckResource] = useState<string | null>(null);
  const [safetyAckChecked, setSafetyAckChecked] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationProgressOpen, setGenerationProgressOpen] = useState(false);
  const [workflowEvents, setWorkflowEvents] = useState<WorkflowEvent[]>(initialWorkflowEvents);
  const [workflowMode, setWorkflowMode] = useState<"idle" | "waiting" | "connected" | "demo" | "complete">("idle");
  const [learningGoal, setLearningGoal] = useState("");
  const [confirmedGoal, setConfirmedGoal] = useState<string | null>(null);
  const [clarification, setClarification] = useState<{ reason: string; questions: ClarificationQuestion[] } | null>(null);
  const [clarificationAnswers, setClarificationAnswers] = useState<Record<string, string>>({});
  const goalForGenerationRef = useRef<string | null>(null);
  const [education, setEducation] = useState("本科");
  const [major, setMajor] = useState("");
  const [skills, setSkills] = useState("");
  const [workYears, setWorkYears] = useState(1);
  const [industry, setIndustry] = useState("");
  const [role, setRole] = useState("");
  const [demoMode, setDemoMode] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [apiKeyDialogOpen, setApiKeyDialogOpen] = useState(false);
  const [backendDemoMode, setBackendDemoMode] = useState<boolean | null>(null);
  const [showWorkspaceTopButton, setShowWorkspaceTopButton] = useState(false);
  const reducedMotion = useReducedMotion();
  const workspaceScrollRef = useRef<HTMLElement>(null);
  const generationFormRef = useRef<HTMLFormElement>(null);
  const stopWorkflowRef = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (!workspaceOpen) setShowWorkspaceTopButton(false);
  }, [workspaceOpen]);
  useEffect(() => {
    if (!workspaceDialog) {
      setActiveStep(null);
      setSelectedQualityGate(null);
    }
  }, [workspaceDialog]);
  useEffect(() => {
    if (!selectedResource) return;
    const resource = (generationResult?.resources ?? []).find(
      (item) => item.resource_type === selectedResource,
    );
    if (!resource || resource.risk_level !== "high_risk") return;
    const key = quizAttemptKey(resource);
    if (hasAcknowledgedSafety(key)) return;
    setSafetyAckChecked(false);
    setSafetyAckResource(key);
  }, [selectedResource, generationResult]);
  const confirmSafetyAck = () => {
    if (!safetyAckResource || !safetyAckChecked) return;
    acknowledgeSafety(safetyAckResource);
    setSafetyAckResource(null);
    setSafetyAckChecked(false);
  };
  useEffect(() => () => stopWorkflowRef.current?.(), []);
  useEffect(() => {
    let cancelled = false;
    fetch(`${getApiBase()}/api/knowledge/core-map`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`))))
      .then((data: CoreMap) => { if (!cancelled) setCoreMap(data); })
      .catch(() => { if (!cancelled) setCoreMap({ domains: [] }); });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    let cancelled = false;
    fetch(`${getApiBase()}/health`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`))))
      .then((health: { demo_mode?: boolean }) => { if (!cancelled && typeof health.demo_mode === "boolean") setBackendDemoMode(health.demo_mode); })
      .catch(() => { /* 后端未启动或 /health 不可用，保持未知 */ });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    if (!generationResult?.task_id || generationResult.status === "completed") return;
    stopWorkflowRef.current?.();
    setWorkflowMode("connected");
    stopWorkflowRef.current = subscribeWorkflow(
      generationResult.task_id,
      (incoming) => setWorkflowEvents((current) => mergeWorkflowEvent(current, incoming)),
      () => setWorkflowMode("waiting"),
    );
    return () => stopWorkflowRef.current?.();
  }, [generationResult?.status, generationResult?.task_id]);
  const schemeB = variant === "b";
  const pointerX = useSpring(useMotionValue(0), { damping: 24, stiffness: 140, mass: 0.45 });
  const pointerY = useSpring(useMotionValue(0), { damping: 24, stiffness: 140, mass: 0.45 });
  const videoX = useTransform(pointerX, [-0.5, 0.5], [-16, 16]);
  const videoY = useTransform(pointerY, [-0.5, 0.5], [-12, 12]);
  const mainX = useTransform(pointerX, [-0.5, 0.5], [-7, 7]);
  const mainY = useTransform(pointerY, [-0.5, 0.5], [-6, 6]);
  const handlePointerMove = (event: MouseEvent<HTMLElement>) => {
    if (reducedMotion || window.matchMedia("(pointer: coarse)").matches) return;
    const rect = event.currentTarget.getBoundingClientRect();
    pointerX.set((event.clientX - rect.left) / rect.width - 0.5);
    pointerY.set((event.clientY - rect.top) / rect.height - 0.5);
  };
  const resetPointer = () => {
    pointerX.set(0);
    pointerY.set(0);
  };
  const scrollWorkspaceToTop = () => {
    workspaceScrollRef.current?.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
  };
  const selectWorkspaceResource = (value: string) => {
    setSelectedResource(value);
    requestAnimationFrame(scrollWorkspaceToTop);
  };
  const closeWorkspaceDialog = () => {
    setWorkspaceDialog(null);
    setActiveStep(null);
    setSelectedQualityGate(null);
  };
  const applyRevision = (resourceType: string, response: LearnerQuestionResponse) => {
    setGenerationResult((current) => current ? {
      ...current,
      resources: (current.resources ?? []).map((resource) => {
        if (resource.resource_type !== resourceType || (resource.content || "").includes(`## ${response.revisionTitle}`)) {
          return resource;
        }
        return {
        ...resource,
        content: (resource.content || "") + "\n\n## " + response.revisionTitle + "\n\n" + response.revisionContent,
        supplements: [...(resource.supplements ?? []), { title: response.revisionTitle, content: response.revisionContent }],
        key_takeaways: [...(resource.key_takeaways ?? []), "已根据你的学习疑问补充说明"],
        };
      }),
    } : current);
  };
  const applyQuizAnswerKey = (resourceId: string | undefined, quiz: Quiz) => {
    setGenerationResult((current) => current ? {
      ...current,
      resources: (current.resources ?? []).map((resource) => {
        const matchesCurrentQuiz = resourceId
          ? resource.resource_id === resourceId
          : resource.resource_type === "quiz";
        return matchesCurrentQuiz ? { ...resource, quiz } : resource;
      }),
    } : current);
  };
  const updateQuizAttempt = (resource: GeneratedResource, update: (current: QuizAttempt) => QuizAttempt) => {
    const key = quizAttemptKey(resource);
    setQuizAttempts((current) => ({
      ...current,
      [key]: update(current[key] ?? createQuizAttempt()),
    }));
  };
  const generateAdaptiveQuiz = async (submission: QuizSubmissionResult) => {
    const apiBase = getApiBase();
    const knowledgeMap = submission.adaptive_profile?.knowledge_map ?? {};
    const topicScores = Object.fromEntries(
      Object.entries(knowledgeMap).map(([knowledgeId, record]) => [knowledgeId, Number(record.mastery ?? 50)]),
    );
    const round = (submission.adaptive_profile?.quiz_history?.length ?? 1) + 1;
    const goal = decodeEscapedText(topic.trim() || learningGoal.trim());
    if (!goal) throw new Error("A learning goal is required before the next quiz can be generated.");

    const payload = {
      learning_goal: goal,
      education_level: ({ "本科": "bachelor", "硕士": "master", "博士": "phd", "其他": "high_school" } as Record<string, string>)[education] ?? "bachelor",
      major: major.trim(),
      work_years: workYears,
      industry: industry.trim(),
      positions: role ? [role.trim()] : [],
      skills_used: skills.split(/[,，]/).map((skill) => skill.trim()).filter(Boolean),
      pretest_results: [{
        test_name: `adaptive_quiz_round_${round}`,
        total_score: submission.score,
        max_score: 100,
        topic_scores: topicScores,
      }],
      resource_types: ["quiz"],
    };

    setIsGenerating(true);
    stopWorkflowRef.current?.();
    setWorkflowEvents(initialWorkflowEvents());
    setWorkflowMode("waiting");
    setGenerationError(null);
    setGenerationProgressOpen(true);

    try {
      const startResponse = await fetch(`${apiBase}/api/generate/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!startResponse.ok) throw new Error(`API ${startResponse.status}`);
      const start = await startResponse.json() as { task_id?: string };
      if (!start.task_id) throw new Error("The API did not return a task id");

      setWorkflowMode("connected");
      stopWorkflowRef.current = subscribeWorkflow(
        start.task_id,
        (incoming) => setWorkflowEvents((current) => mergeWorkflowEvent(current, incoming)),
        () => undefined,
      );

      let task: { status?: string; result?: GenerationResult; error?: string } | null = null;
      for (let attempt = 0; attempt < 720; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        const taskResponse = await fetch(`${apiBase}/api/tasks/${encodeURIComponent(start.task_id)}`);
        if (!taskResponse.ok) throw new Error(`Task API ${taskResponse.status}`);
        task = await taskResponse.json() as { status?: string; result?: GenerationResult; error?: string };
        if (task.status === "completed" && task.result) break;
        if (["error", "failed", "cancelled"].includes(task.status ?? "")) {
          throw new Error(task.error || "下一轮针对性测试生成失败。");
        }
      }
      if (!task?.result) throw new Error("The next quiz did not finish in time");

      const result = { ...task.result, mode: "api" as const };
      setWorkflowEvents((current) => (result.agent_log ?? []).reduce(
        (events, item) => mergeWorkflowEvent(events, {
          agent: item.agent || "generation",
          status: item.status === "error" ? "error" : "done",
          message: item.status === "error" ? "Error" : "Complete",
        }),
        current,
      ));
      setWorkflowMode("complete");
      const incomingResources = result.resources ?? [];
      const includesQuiz = incomingResources.some(isQuizResource);
      setGenerationResult((current) => {
        const existingResources = current?.resources ?? [];
        let nextRound = existingResources.filter(isQuizResource).length + 1;
        const appendedResources = incomingResources.map((resource) => {
          if (!isQuizResource(resource)) return resource;
          const resourceType = `quiz_round_${nextRound}`;
          nextRound += 1;
          return { ...resource, resource_type: resourceType };
        });
        const appendedAudit = (result.audit ?? []).map((item) => {
          const generatedIndex = item.resource_index ?? 0;
          const generatedResource = appendedResources[generatedIndex];
          return {
            ...item,
            resource_index: existingResources.length + generatedIndex,
            resource_type: generatedResource?.resource_type ?? item.resource_type,
          };
        });
        return {
          ...(current ?? {}),
          ...result,
          diagnosis: result.diagnosis ?? current?.diagnosis,
          resources: [...existingResources, ...appendedResources],
          audit: [...(current?.audit ?? []), ...appendedAudit],
          agent_log: [...(current?.agent_log ?? []), ...(result.agent_log ?? [])],
        };
      });
      setResourceReady(true);
      setSelectedResource(includesQuiz ? "quiz" : incomingResources[0]?.resource_type ?? "quiz");
    } catch (error) {
      const message = generationTaskErrorMessage(error);
      setGenerationError(message);
      setWorkflowMode("idle");
      throw new Error(message);
    } finally {
      stopWorkflowRef.current?.();
      setIsGenerating(false);
      setGenerationProgressOpen(false);
    }
  };
  const exportGeneratedResources = () => {
    const resources = generationResult?.resources ?? [];
    if (!resources.length) return;

    const exportTopic = topic.trim() || "个性化学习";
    const diagnosis = generationResult?.diagnosis;
    const skillGaps = (diagnosis?.skill_gaps ?? [])
      .map((gap) => gap.topic)
      .filter((gap): gap is string => Boolean(gap))
      .join("、");
    const resourceSections = resources.map((resource, index) => {
      const quiz = resource.quiz ?? (hasQuizSignals(resource) ? parseQuizContent(resource) : null);
      const roundNumber = isQuizResource(resource) ? quizRoundNumber(resources, resource) : null;
      const sectionLabel = roundNumber ? `\u7b2c ${roundNumber} \u8f6e\u6d4b\u8bd5` : resourceLabel(resource.resource_type);
      const takeaways = (resource.key_takeaways ?? []).filter(Boolean);
      const supplements = getResourceSupplements(resource);
      const baseContent = getExportBaseContent(resource, supplements);
      const content = quiz ? renderQuizDocumentForExport(quiz) : renderDocumentMarkdown(baseContent);
      const takeawaysMarkup = takeaways.length
        ? `<section class="takeaways"><h3>学习重点</h3><ul>${takeaways.map((item) => `<li>${escapeDocumentHtml(item)}</li>`).join("")}</ul></section>`
        : "";
      const supplementsMarkup = supplements.length
        ? `<section class="supplements"><h3>针对学习疑问的补充资源</h3>${supplements.map((supplement) => `<article class="supplement"><h4>${escapeDocumentHtml(supplement.title)}</h4><section class="content">${renderDocumentMarkdown(supplement.content)}</section></article>`).join("")}</section>`
        : "";

      return `<section class="resource"><h2>${index + 1}. ${escapeDocumentHtml(sectionLabel)}</h2><h3>${escapeDocumentHtml(resource.title || sectionLabel)}</h3><p class="meta">难度：${escapeDocumentHtml(resource.difficulty_level || "未提供")}　预计时长：${resource.estimated_duration_minutes ? `${resource.estimated_duration_minutes} 分钟` : "未提供"}</p>${takeawaysMarkup}<section class="content">${content}</section>${supplementsMarkup}</section>`;
    }).join("");
    const auditItems = (generationResult?.audit ?? []).map((item) => {
      const issues = (item.issues ?? []).map((issue) => issue.detail).filter((detail): detail is string => Boolean(detail)).join("；");
      return `<li><strong>${escapeDocumentHtml(resourceLabel(item.resource_type || "资源"))}：</strong>${escapeDocumentHtml(item.verdict || "未提供")}${issues ? `（${escapeDocumentHtml(issues)}）` : ""}</li>`;
    }).join("");
    const documentTitle = `${exportTopic} - 个性化学习资源`;
    const documentHtml = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8" /><title>${escapeDocumentHtml(documentTitle)}</title><style>@page{size:A4;margin:18mm}body{color:#172b3a;font-family:"Microsoft YaHei",Arial,sans-serif;font-size:11pt;line-height:1.75}h1,h2,h3,h4{color:#172b3a;margin:0}h1{font-size:22pt}h2{font-size:16pt;margin-top:0}h3{font-size:13pt;margin-top:8pt}h4{font-size:11pt;margin-top:12pt}.meta{color:#5d6a75;font-size:9.5pt}.summary,.audit{background:#f2f4f7;border-left:4px solid #7342e2;padding:12pt 16pt;margin:18pt 0}.resource{border-top:1px solid #d7dce1;margin-top:22pt;padding-top:18pt}.takeaways{background:#f8f6ff;padding:10pt 14pt;margin:14pt 0}.supplements{background:#f8f6ff;border-left:4px solid #7342e2;margin:14pt 0;padding:10pt 14pt}.supplement+.supplement{border-top:1px solid #e3e6e9;margin-top:12pt;padding-top:12pt}.content p{margin:9pt 0}.quiz{margin-top:10pt}.question{border-top:1px solid #e3e6e9;margin-top:14pt;padding-top:12pt}ol,ul{padding-left:22pt}li{margin:4pt 0}</style></head><body><h1>${escapeDocumentHtml(documentTitle)}</h1><p class="meta">导出时间：${escapeDocumentHtml(new Date().toLocaleString("zh-CN"))}</p><section class="summary"><h2>学习画像</h2><p><strong>学习目标：</strong>${escapeDocumentHtml(exportTopic)}</p><p><strong>诊断摘要：</strong>${escapeDocumentHtml(diagnosis?.summary || "暂无诊断摘要。")}</p><p><strong>推荐难度：</strong>${escapeDocumentHtml(diagnosis?.recommended_difficulty || "未提供")}</p>${skillGaps ? `<p><strong>待补足方向：</strong>${escapeDocumentHtml(skillGaps)}</p>` : ""}</section>${resourceSections}${auditItems ? `<section class="audit"><h2>审核摘要</h2><ul>${auditItems}</ul></section>` : ""}</body></html>`;
    const safeFileName = exportTopic.replace(/[\\/:*?"<>|]/g, "_").slice(0, 60) || "学习资源";
    const blob = new Blob(["\ufeff", documentHtml], { type: "application/msword;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${safeFileName}.doc`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };
  const confirmClarification = () => {
    const refined = refineLearningGoal(learningGoal, clarificationAnswers);
    // React state is asynchronous; retain the exact clarified goal for this request.
    goalForGenerationRef.current = refined;
    setLearningGoal(refined);
    setTopic(refined);
    setConfirmedGoal(refined);
    setClarification(null);
    requestAnimationFrame(() => generationFormRef.current?.requestSubmit());
  };
  const selectPanel = (index: number) => setActivePanel(panelIds[index] ?? "overview");
  const openGenerator = () => {
    if (!topic && learningGoal) setTopic(learningGoal);
    setResourceReady(false);
    setGenerationError(null);
    setGeneratorOpen(true);
  };
  const submitGenerationLegacy = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (confirmedGoal !== learningGoal.trim()) {
      const assessment = await assessLearningGoal(learningGoal);
      if (assessment.status === "needs_clarification") {
        setClarification({ reason: assessment.reason, questions: assessment.questions });
        setClarificationAnswers({});
        return;
      }
      setConfirmedGoal(learningGoal.trim());
    }
    setIsGenerating(true);
    stopWorkflowRef.current?.();
    setWorkflowEvents(initialWorkflowEvents());
    setWorkflowMode("waiting");
    setGenerationError(null);
    setGeneratorOpen(false);
    setGenerationProgressOpen(true);
    const payload = {
      learning_goal: learningGoal.trim(),
      education_level: ({ "本科": "bachelor", "硕士": "master", "博士": "phd", "其他": "high_school" } as Record<string, string>)[education] ?? "bachelor",
      major: major.trim(),
      work_years: workYears,
      industry: industry.trim(),
      positions: role ? [role.trim()] : [],
      skills_used: skills.split(/[,，]/).map((skill) => skill.trim()).filter(Boolean),
      pretest_results: [],
      resource_types: resourceTypes,
    };
    let result: GenerationResult;
    try {
      if (demoMode) throw new Error("demo mode");
      const response = await fetch(`${getApiBase()}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(`API ${response.status}`);
      result = { ...(await response.json() as GenerationResult), mode: "api" };
    } catch {
      setWorkflowMode("demo");
      stopWorkflowRef.current = simulateWorkflow((incoming) => setWorkflowEvents((current) => mergeWorkflowEvent(current, incoming)));
      await new Promise((resolve) => window.setTimeout(resolve, workflowStages.length * 620 + 500));
      result = {
        mode: "demo",
        status: "completed",
        diagnosis: { summary: `未连接到本地 API，以下为“${learningGoal}”的演示结果。`, learning_style: "practice_first", recommended_difficulty: "beginner", skill_gaps: [{ topic: learningGoal, priority: "high" }] },
        resources: resourceTypes.map((type) => ({ resource_type: type, title: `${resourceLabel(type)}：${learningGoal}`, content: `# ${learningGoal}\n\n这是 XH-agent 本地演示资源。启动后端后将由 Agent 1 学情诊断、Agent 2 知识生成、Agent 3 内容审核返回真实内容。`, difficulty_level: "beginner", estimated_duration_minutes: type === "quiz" ? 15 : 30, risk_level: "theory", safety_warnings: [] })),
        audit: resourceTypes.map((type, index) => ({ resource_index: index, resource_type: type, verdict: "approved" })),
        agent_log: [{ agent: "diagnosis", status: "done" }, { agent: "generation", status: "done" }, { agent: "audit", status: "done" }],
      };
    }
    if (result.mode === "api") {
      setWorkflowEvents((current) => (result.agent_log ?? []).reduce((events, item) => { const agent = item.agent || "generation"; const existing = events.find((event) => event.agent === agent); return mergeWorkflowEvent(events, { agent, status: item.status === "error" ? "error" : "done", message: existing?.message || (item.status === "error" ? "异常" : "已完成") }); }, current));
      if (result.status === "completed") setWorkflowMode("complete");
    }
    setGenerationResult(result);
    setQuizAttempts({});
    setResourceReady(true);
    setSelectedResource(result.resources?.[0]?.resource_type ?? resourceTypes[0] ?? null);
    setIsGenerating(false);
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    setGenerationProgressOpen(false);
    setGeneratorOpen(false);
    setWorkspaceOpen(true);
  };
  const performGeneration = async (goalForGeneration: string) => {
    const apiBase = getApiBase();
    const payload = {
      learning_goal: goalForGeneration,
      education_level: ({ "本科": "bachelor", "硕士": "master", "博士": "phd", "其他": "high_school" } as Record<string, string>)[education] ?? "bachelor",
      major: major.trim(),
      work_years: workYears,
      industry: industry.trim(),
      positions: role ? [role.trim()] : [],
      skills_used: skills.split(/[,，]/).map((skill) => skill.trim()).filter(Boolean),
      pretest_results: [],
      resource_types: resourceTypes,
    };

    setIsGenerating(true);
    stopWorkflowRef.current?.();
    setWorkflowEvents(initialWorkflowEvents());
    setWorkflowMode("waiting");
    setGenerationError(null);
    setGeneratorOpen(false);
    setGenerationProgressOpen(true);

    let result: GenerationResult;
    try {
      if (demoMode) throw new Error("Demo mode selected");
      if (apiKey.trim()) {
        const keyResponse = await fetch(`${apiBase}/api/config/llm-key`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ api_key: apiKey.trim() }),
        });
        if (!keyResponse.ok) throw new Error(`API Key 配置失败 ${keyResponse.status}`);
        const keyResult = await keyResponse.json() as { demo_mode?: boolean };
        if (typeof keyResult.demo_mode === "boolean") setBackendDemoMode(keyResult.demo_mode);
      }
      const startResponse = await fetch(`${apiBase}/api/generate/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!startResponse.ok) throw new Error(`API ${startResponse.status}`);
      const start = await startResponse.json() as { task_id?: string };
      if (!start.task_id) throw new Error("The API did not return a task id");

      setWorkflowMode("connected");
      setWorkflowEvents((current) => mergeWorkflowEvent(current, {
        task_id: start.task_id,
        agent: "diagnosis",
        status: "running",
        message: "任务已创建，正在开始学情诊断",
      }));
      stopWorkflowRef.current = subscribeWorkflow(
        start.task_id,
        (incoming) => setWorkflowEvents((current) => mergeWorkflowEvent(current, incoming)),
        () => undefined,
      );

      let task: { status?: string; result?: GenerationResult; error?: string } | null = null;
      for (let attempt = 0; attempt < 720; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 500));
        const taskResponse = await fetch(`${apiBase}/api/tasks/${encodeURIComponent(start.task_id)}`);
        if (!taskResponse.ok) throw new Error(`Task API ${taskResponse.status}`);
        task = await taskResponse.json() as { status?: string; result?: GenerationResult; error?: string };
        if (task.status === "completed" && task.result) break;
        if (task.status === "error") throw new Error(task.error || "Generation failed");
      }
      if (!task?.result) throw new Error("The task did not finish in time");
      result = { ...task.result, mode: "api" };
    } catch {
      setWorkflowMode("demo");
      stopWorkflowRef.current = simulateWorkflow((incoming) => setWorkflowEvents((current) => mergeWorkflowEvent(current, incoming)));
      await new Promise((resolve) => window.setTimeout(resolve, workflowStages.length * 620 + 500));
      result = {
        mode: "demo",
        status: "completed",
        diagnosis: { summary: `本地 API 未连接，以下为 ${learningGoal} 的演示学习画像。`, learning_style: "practice_first", recommended_difficulty: "beginner", skill_gaps: [{ topic: learningGoal, priority: "high" }] },
        resources: resourceTypes.map((type) => ({ resource_type: type, title: `${resourceLabel(type)}：${learningGoal}`, content: `# ${learningGoal}\n\n这是 XH-agent 的本地演示资源。连接后端后会显示真实 Agent 生成内容。`, difficulty_level: "beginner", estimated_duration_minutes: type === "quiz" ? 15 : 30, risk_level: "theory", safety_warnings: [] })),
        audit: resourceTypes.map((type, index) => ({ resource_index: index, resource_type: type, verdict: "approved" })),
        agent_log: workflowStages.map((stage) => ({ agent: stage.agent, status: "done" })),
      };
    }

    setWorkflowEvents((current) => (result.agent_log ?? []).reduce(
      (events, item) => {
        const agent = item.agent || "generation";
        const existing = events.find((event) => event.agent === agent);
        return mergeWorkflowEvent(events, {
          agent,
          status: item.status === "error" ? "error" : "done",
          message: existing?.message || (item.status === "error" ? "执行失败" : "已完成"),
        });
      },
      current,
    ));
    setWorkflowMode("complete");
    setGenerationResult(result);
    setGenerationSeq((n) => n + 1);
    setQuizAttempts({});
    setResourceReady(true);
    setSelectedResource(result.resources?.[0]?.resource_type ?? resourceTypes[0] ?? null);
    setIsGenerating(false);
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    setGenerationProgressOpen(false);
    setWorkspaceOpen(true);
  };
  const submitGeneration = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const goalForGeneration = goalForGenerationRef.current ?? learningGoal.trim();
    if (confirmedGoal !== goalForGeneration) {
      const assessment = await assessLearningGoal(goalForGeneration);
      if (assessment.status === "needs_clarification") {
        setClarification({ reason: assessment.reason, questions: assessment.questions });
        setClarificationAnswers({});
        return;
      }
      setConfirmedGoal(goalForGeneration);
    }
    goalForGenerationRef.current = null;
    await performGeneration(goalForGeneration);
  };
  const toggleResourceType = (item: string) => {
    setResourceTypes((current) => current.includes(item) ? (current.length === 1 ? current : current.filter((type) => type !== item)) : [...current, item]);
  };
  const openApiKeyDialog = () => {
    setDemoMode(false);
    setApiKeyDialogOpen(true);
  };
  const fadeUp = (index: number) => ({
    initial: reducedMotion ? false : { opacity: 0, y: 28 },
    animate: { opacity: 1, y: 0 },
    transition: { delay: index * 0.15, duration: 0.6, ease },
  });

  return (
    <section className={`relative isolate min-h-[100dvh] overflow-hidden bg-[#F2F2EE] font-[var(--font-body)] text-[#192837] ${schemeB ? "scheme-b" : "scheme-a"}`} onMouseLeave={resetPointer} onMouseMove={handlePointerMove}>
      <motion.video autoPlay className="absolute inset-[-16px] z-0 h-[calc(100%+32px)] w-[calc(100%+32px)] object-cover" loop muted playsInline preload="metadata" style={reducedMotion ? undefined : { x: videoX, y: videoY }}>
        <source src="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260518_003132_8b7edcb6-c64d-4a52-a9ca-879942e122ad.mp4" type="video/mp4" />
      </motion.video>
      <div className="absolute inset-0 z-[1] bg-[#F2F2EE]/[0.14]" />

      <header className="relative z-50 mx-auto flex max-w-[1280px] items-center gap-3 px-5 py-4 max-[1023px]:[&>div]:hidden lg:gap-4 lg:[&>div>button]:px-3 lg:[&>div>button]:py-2 lg:[&>div>button]:text-xs xl:[&>div>button]:px-5 xl:[&>div>button]:py-2.5 xl:[&>div>button]:text-sm sm:px-8 sm:py-5">
        {!schemeB ? <BrandMark /> : null}
        <nav className="hidden shrink-0 items-center gap-5 text-[15px] lg:flex xl:gap-7 xl:text-base" aria-label="Primary navigation">
          {navigation.map((item, index) => <button className={`relative whitespace-nowrap px-1 py-2 font-semibold leading-none transition-colors after:absolute after:bottom-0 after:left-1/2 after:h-0.5 after:w-4 after:-translate-x-1/2 after:rounded-full after:transition-transform ${activePanel === panelIds[index] ? "text-[#192837] after:scale-x-100 after:bg-[#7342E2]" : "text-[#192837]/60 after:scale-x-0 hover:text-[#192837]"}`} key={item} onClick={() => selectPanel(index)} type="button">{item}</button>)}
        </nav>
        <GlobalSearch />
        <div className="ml-auto hidden shrink-0 items-center gap-2 md:flex"><ActionButton kind="accent" onClick={openGenerator}>生成学习资源</ActionButton><ActionButton kind="quiet" onClick={() => setWorkspaceOpen(true)}>进入工作台</ActionButton></div>
        <button aria-expanded={menuOpen} aria-label="打开菜单" className="grid h-10 w-10 place-items-center rounded-full bg-[#F2F2EE]/85 md:hidden" onClick={() => setMenuOpen(true)}><Menu size={21} strokeWidth={1.8} /></button>
      </header>

      <button aria-expanded={menuOpen} aria-label="打开菜单" className="absolute left-5 top-4 z-20 hidden h-10 w-10 place-items-center rounded-full bg-[#F2F2EE]/85 md:grid lg:hidden sm:left-8 sm:top-5" onClick={() => setMenuOpen(true)} type="button"><Menu size={21} strokeWidth={1.8} /></button>
      <div className={`relative z-10 mx-auto max-w-[1280px] px-5 sm:px-8 ${schemeB ? "lg:flex lg:items-end lg:justify-start lg:gap-6" : ""}`} style={{ paddingTop: "clamp(40px, 8vw, 72px)" }}>
        <motion.div className={schemeB ? "max-w-[560px] rounded-[2rem] bg-[#F2F2EE]/78 p-7 shadow-[0_18px_60px_rgba(25,40,55,0.10)] backdrop-blur-[3px] sm:p-10" : "max-w-[560px]"} style={reducedMotion ? undefined : { x: mainX, y: mainY }}>
          <motion.h1 {...fadeUp(0)} className="mb-6 font-[var(--font-heading)] text-[clamp(1.65rem,5vw,3rem)] font-bold leading-[1.05] tracking-[-0.01em]">领域知识个性化生成与多智能体协同决策系统</motion.h1>
          <motion.p {...fadeUp(1)} className="max-w-[560px] text-[clamp(0.9rem,2.5vw,1.1rem)] leading-[1.65] opacity-80">从目标追问到实时协同：XH-Agent 基于知识库检索生成讲义、实操指南与可作答测试题，并完成质量审核、保真修正与后续答疑。</motion.p>
          <motion.button {...fadeUp(2)} className="mt-8 flex min-w-[210px] max-w-max items-center justify-between gap-8 rounded-[50px] bg-[#7342E2] px-6 py-[17px] text-[clamp(0.9rem,2vw,1rem)] font-semibold text-white shadow-[0_4px_24px_rgba(115,66,226,0.28)]" onClick={openGenerator} type="button" whileHover={{ scale: 1.04, filter: "brightness(1.1)" }} whileTap={{ scale: 0.96 }}>
            开始定制学习方案 <ArrowRightCircle size={20} strokeWidth={1.8} />
          </motion.button>
        </motion.div>
        {schemeB ? (
          <motion.aside className="mt-10 hidden w-[270px] shrink-0 rounded-[1.75rem] bg-[#F2F2EE]/82 p-6 text-[#192837] shadow-[0_18px_60px_rgba(25,40,55,0.12)] backdrop-blur-[4px] lg:mt-0 lg:block" style={reducedMotion ? undefined : { x: mainX, y: mainY }} aria-label="XH Agent 工作流">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#192837]/55">协同工作流</p>
            <h2 className="mt-2 font-[var(--font-heading)] text-2xl leading-tight">从目标澄清到学习闭环</h2>
            <button className="mt-5 flex w-full items-center justify-between rounded-xl bg-[#192837]/[0.08] px-3 py-2 text-left text-xs font-semibold transition hover:bg-[#7342E2] hover:text-white" onClick={() => setHomeInfoDialog("workflow")} type="button"><span>查看流程说明</span><ArrowRightCircle size={16} strokeWidth={1.8} /></button>
            <ol className="mt-4 grid gap-4">
              {workflowSteps.map((step, index) => (
                <motion.li className="flex cursor-default items-center gap-3 text-sm" key={step} onHoverEnd={() => setActiveStep(null)} onHoverStart={() => setActiveStep(index)} whileHover={reducedMotion ? undefined : { x: 4, scale: 1.02 }}>
                  <span className={`grid h-7 w-7 place-items-center rounded-full text-xs font-semibold transition-colors ${activeStep === index ? "bg-[#7342E2] text-white" : "bg-[#192837]/[0.08]"}`}>0{index + 1}</span>
                  <span className="font-medium">{step}</span>
                </motion.li>
              ))}
            </ol>
          </motion.aside>
        ) : null}
      </div>
      <motion.section key={activePanel} aria-live="polite" className="relative z-10 mx-auto mt-10 max-w-[1280px] px-5 pb-10 sm:px-8" initial={reducedMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} style={schemeB && !reducedMotion ? { x: mainX, y: mainY } : undefined} transition={{ duration: 0.35, ease }}>
        <div className="max-w-[720px] rounded-[1.5rem] bg-[#F2F2EE]/70 p-6 shadow-[0_14px_42px_rgba(25,40,55,0.08)] backdrop-blur-[3px] sm:p-7">
          <p className="text-xs font-semibold tracking-[0.12em] text-[#192837]/55">{panelDetails[activePanel].eyebrow}</p>
          <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="font-[var(--font-heading)] text-2xl leading-tight">{panelDetails[activePanel].title}</h2>
              <p className="mt-2 max-w-[540px] text-sm leading-6 text-[#192837]/75">{panelDetails[activePanel].description}</p>
            </div>
            {activePanel === "overview" ? <button className="shrink-0 rounded-full bg-[#192837]/[0.08] px-3 py-2 text-xs font-semibold transition hover:bg-[#7342E2] hover:text-white" onClick={() => setHomeInfoDialog("overview")} type="button">查看系统说明</button> : <span className="shrink-0 rounded-full bg-[#192837]/[0.08] px-3 py-2 text-xs font-semibold">{panelDetails[activePanel].metric}</span>}
          </div>
        </div>
      </motion.section>
      <MobileMenu onNavigate={selectPanel} onOpenGenerator={openGenerator} onOpenWorkspace={() => { setMenuOpen(false); setWorkspaceOpen(true); }} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <AnimatePresence>
        {homeInfoDialog ? (
          <>
            <motion.button aria-label="关闭说明弹窗" className="fixed inset-0 z-50 bg-[#192837]/40 backdrop-blur-[4px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setHomeInfoDialog(null)} type="button" />
            <motion.section aria-label={homeInfoDialog === "workflow" ? "协同工作流说明" : "系统概览说明"} className="fixed inset-x-4 top-1/2 z-[55] mx-auto max-h-[calc(100dvh-48px)] w-[min(680px,calc(100vw-32px))] -translate-y-1/2 overflow-y-auto rounded-[2rem] bg-[#F2F2EE] p-6 text-[#192837] shadow-[0_22px_72px_rgba(25,40,55,0.30)] sm:p-8" initial={reducedMotion ? false : { opacity: 0, y: 22, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 22, scale: 0.98 }} transition={{ duration: 0.3, ease }} role="dialog" aria-modal="true">
              <div className="flex items-start justify-between gap-5">
                <div>
                  <p className="text-xs font-semibold tracking-[0.12em] text-[#192837]/55">{homeInfoDialog === "workflow" ? "协同工作流" : "系统概览"}</p>
                  <h2 className="mt-2 font-[var(--font-heading)] text-3xl leading-tight">{homeInfoDialog === "workflow" ? "每一步都有明确输入与输出" : "把学习目标变成可验证的进步"}</h2>
                </div>
                <button aria-label="关闭" className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#192837]/[0.08] transition hover:bg-[#192837]/[0.15]" onClick={() => setHomeInfoDialog(null)} type="button"><X size={20} strokeWidth={1.8} /></button>
              </div>
              {homeInfoDialog === "workflow" ? (
                <div className="mt-7 grid gap-3">
                  <p className="text-sm leading-6 text-[#192837]/75">XH-Agent 会把一次学习请求拆成连续协作的任务。前一阶段的结论会成为后一阶段的依据，避免资源内容与学习目标脱节。</p>
                  {["目标澄清：补齐学习范围、预期成果与时间边界。", "学情诊断：结合已有技能、专业和工作背景确定起点。", "知识检索与资源生成：从知识库检索相关内容，再生成讲义、实操指南或测试题。", "内容审核与保真修正：检查资源是否有依据、难度是否匹配、表述是否可用。", "学习反馈：根据答题结果和学习疑问，补充解释、建议或下一轮资源。"].map((item, index) => <div className="flex gap-3 rounded-2xl bg-white/65 p-4" key={item}><span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#7342E2] text-xs font-semibold text-white">0{index + 1}</span><p className="text-sm font-medium leading-6">{item}</p></div>)}
                </div>
              ) : (
                <div className="mt-7 grid gap-4">
                  <p className="text-sm leading-6 text-[#192837]/75">系统概览展示项目如何从一个宽泛的学习愿望，逐步形成能学习、能练习、能反馈的个性化路径。</p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {["明确目标：先识别过于宽泛的目标，并通过追问确定重点、成果和周期。", "可信生成：检索本地知识库，以检索结果约束讲义、实操指南与测试题。", "可验证练习：测试题支持提交作答，再显示标准答案与解析。", "反馈迭代：学习者可以提出疑问，系统据此生成针对性补充与下一步建议。"].map((item, index) => <div className="rounded-2xl bg-white/65 p-4" key={item}><span className="text-xs font-semibold text-[#7342E2]">0{index + 1}</span><p className="mt-2 text-sm font-medium leading-6">{item}</p></div>)}
                  </div>
                  <div className="rounded-2xl bg-[#192837] p-5 text-white"><p className="text-xs font-semibold text-white/55">学习闭环</p><p className="mt-2 text-sm leading-6 text-white/85">目标澄清、学情诊断、知识检索、资源生成、审核修正、作答与反馈构成持续迭代的学习闭环。每次反馈都能成为下一次学习资源生成的输入。</p></div>
                </div>
              )}
              <button className="mt-7 w-full rounded-full bg-[#7342E2] px-5 py-3 text-sm font-semibold text-white shadow-[0_4px_20px_rgba(115,66,226,0.25)] transition hover:brightness-110" onClick={() => setHomeInfoDialog(null)} type="button">我知道了</button>
            </motion.section>
          </>
        ) : null}
      </AnimatePresence>
      <AnimatePresence>
        {generatorOpen ? (
          <>
            <motion.button aria-label="关闭资源生成面板" className="fixed inset-0 z-30 bg-[#192837]/35 backdrop-blur-[4px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setGeneratorOpen(false)} type="button" />
            <motion.section aria-label="生成学习资源" className="fixed inset-x-3 bottom-3 top-3 z-40 mx-auto max-w-[760px] overflow-y-auto rounded-[2rem] bg-[#F2F2EE] p-6 text-[#192837] shadow-[0_22px_72px_rgba(25,40,55,0.28)] sm:inset-x-auto sm:bottom-auto sm:right-8 sm:top-1/2 sm:max-h-[calc(100dvh-48px)] sm:w-[min(720px,calc(100vw-64px))] sm:-translate-y-1/2 sm:p-8" initial={reducedMotion ? false : { opacity: 0, y: 28 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 28 }} transition={{ duration: 0.35, ease }} role="dialog" aria-modal="true">
              <div className="flex items-start justify-between gap-5">
                <div><p className="text-xs font-semibold tracking-[0.12em] text-[#192837]/55">学习画像</p><h2 className="mt-2 font-[var(--font-heading)] text-3xl leading-tight">先了解你的学习需求</h2></div>
                <button aria-label="关闭" className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#192837]/[0.08]" onClick={() => setGeneratorOpen(false)} type="button"><X size={20} strokeWidth={1.8} /></button>
              </div>
              <form className="mt-7 grid gap-7" onSubmit={submitGeneration} ref={generationFormRef}>
                <fieldset className="grid gap-3"><legend className="text-lg font-semibold">学习目标</legend><label className="grid gap-2 text-sm font-medium">希望完成什么学习任务<textarea className="min-h-24 resize-y rounded-xl bg-white/70 px-4 py-3 font-normal outline-none ring-[#7342E2] transition focus:ring-2" onChange={(event) => { setLearningGoal(event.target.value); setTopic(event.target.value); }} placeholder="例如：掌握 LangGraph 多智能体 AI 应用开发" required value={learningGoal} /></label></fieldset>
                <fieldset className="grid gap-4"><legend className="text-lg font-semibold">基本信息</legend><div className="grid gap-3 sm:grid-cols-2"><label className="grid gap-2 text-sm font-medium">学历<select className="rounded-xl bg-white/70 px-3 py-3 font-normal outline-none ring-[#7342E2] transition focus:ring-2" onChange={(event) => setEducation(event.target.value)} value={education}><option>本科</option><option>硕士</option><option>博士</option><option>其他</option></select></label><label className="grid gap-2 text-sm font-medium">专业<input className="rounded-xl bg-white/70 px-3 py-3 font-normal outline-none ring-[#7342E2] transition focus:ring-2" onChange={(event) => setMajor(event.target.value)} placeholder="例如：计算机科学" value={major} /></label></div><label className="grid gap-2 text-sm font-medium">已掌握技能<input className="rounded-xl bg-white/70 px-4 py-3 font-normal outline-none ring-[#7342E2] transition focus:ring-2" onChange={(event) => setSkills(event.target.value)} placeholder="例如：Python、Flask、SQL" value={skills} /></label></fieldset>
                <fieldset className="grid gap-4"><legend className="text-lg font-semibold">工作背景</legend><div className="grid gap-3 sm:grid-cols-2"><label className="grid gap-2 text-sm font-medium">工作年限<span className="text-[#7342E2]">{workYears.toFixed(1)} 年</span><input className="accent-[#7342E2]" max="15" min="0" onChange={(event) => setWorkYears(Number(event.target.value))} step="0.5" type="range" value={workYears} /></label><label className="grid gap-2 text-sm font-medium">所在行业<input className="rounded-xl bg-white/70 px-3 py-3 font-normal outline-none ring-[#7342E2] transition focus:ring-2" onChange={(event) => setIndustry(event.target.value)} placeholder="例如：互联网" value={industry} /></label></div><label className="grid gap-2 text-sm font-medium">岗位<input className="rounded-xl bg-white/70 px-4 py-3 font-normal outline-none ring-[#7342E2] transition focus:ring-2" onChange={(event) => setRole(event.target.value)} placeholder="例如：Python 开发" value={role} /></label></fieldset>
                <fieldset className="grid gap-3"><legend className="text-lg font-semibold">输出设置</legend><span className="text-sm font-medium">资源类型，可多选</span><div className="flex flex-wrap gap-2">{resourceOptions.map((option) => <button aria-pressed={resourceTypes.includes(option.id)} className={`rounded-full px-3 py-2 text-sm font-medium transition ${resourceTypes.includes(option.id) ? "bg-[#7342E2] text-white" : "bg-[#192837]/[0.08] hover:bg-[#192837]/[0.14]"}`} key={option.id} onClick={() => toggleResourceType(option.id)} type="button">{option.label}</button>)}</div><div className="mt-1 grid gap-2"><span className="text-sm font-medium">{"生成方式"}</span><div className="grid gap-2 sm:grid-cols-2"><button aria-pressed={demoMode} className={`rounded-xl px-4 py-3 text-sm font-medium transition ${demoMode ? "bg-[#7342E2] text-white" : "bg-[#192837]/[0.08] hover:bg-[#192837]/[0.14]"}`} onClick={() => setDemoMode(true)} type="button">{"使用演示数据"}</button><button aria-pressed={!demoMode} className={`rounded-xl px-4 py-3 text-sm font-medium transition ${!demoMode ? "bg-[#7342E2] text-white" : "bg-[#192837]/[0.08] hover:bg-[#192837]/[0.14]"}`} onClick={openApiKeyDialog} type="button">{"使用真实 API"}{!demoMode && apiKey ? " · 已填 Key" : ""}</button></div>{!demoMode && !apiKey ? <p className="text-xs text-[#192837]/60">{"真实模式下未填 Key 则使用后端 .env 配置。"}</p> : null}</div></fieldset>
                {generationError ? <p className="text-sm text-red-700">{generationError}</p> : null}
                <button className="mt-1 flex items-center justify-between rounded-full bg-[#7342E2] px-6 py-4 text-left font-semibold text-white shadow-[0_4px_24px_rgba(115,66,226,0.28)] transition hover:brightness-110 disabled:cursor-wait disabled:opacity-60" disabled={isGenerating} type="submit">{isGenerating ? "正在调用 XH-agent..." : "调用 XH-agent 生成"} <ArrowRightCircle size={20} strokeWidth={1.8} /></button>
              </form>
              <AnimatePresence>
                {resourceReady ? <motion.div className="mt-6 rounded-2xl bg-[#192837] p-5 text-white" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}><p className="text-xs font-semibold text-white/55">已准备好</p><h3 className="mt-2 text-lg font-semibold">{resourceTypes.map(resourceLabel).join("、")}：{topic}</h3><p className="mt-2 text-sm leading-6 text-white/75">结果已转入学习工作台。</p></motion.div> : null}
              </AnimatePresence>
            </motion.section>
          </>
        ) : null}
      </AnimatePresence>
      <AnimatePresence>
        {generationProgressOpen ? <GenerationProgressScreen events={workflowEvents} mode={workflowMode} /> : null}
      </AnimatePresence>
      <AnimatePresence>
        {apiKeyDialogOpen ? (
          <>
            <motion.button aria-label="关闭 API Key 弹窗" className="fixed inset-0 z-50 bg-[#192837]/40 backdrop-blur-[4px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setApiKeyDialogOpen(false)} type="button" />
            <motion.section aria-label="配置 API Key" className="fixed left-1/2 top-1/2 z-[60] w-[min(92vw,520px)] -translate-x-1/2 -translate-y-1/2 rounded-[2rem] bg-[#F2F2EE] p-6 text-[#192837] shadow-[0_24px_80px_rgba(25,40,55,0.3)] sm:p-8" initial={reducedMotion ? false : { opacity: 0, y: 20, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 20, scale: 0.97 }} transition={{ duration: 0.3, ease }} role="dialog" aria-modal="true">
              <div className="flex items-start justify-between gap-5"><div><p className="text-xs font-semibold tracking-[0.12em] text-[#192837]/55">{"在线生成"}</p><h2 className="mt-2 font-[var(--font-heading)] text-3xl leading-tight">{"填写 API Key"}</h2></div><button aria-label="关闭" className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#192837]/[0.08]" onClick={() => setApiKeyDialogOpen(false)} type="button"><X size={20} strokeWidth={1.8} /></button></div>
              <p className="mt-4 text-sm leading-6 text-[#192837]/70">{"填入后切换到真实模式，由后端在线调用 LLM 生成资源。Key 仅存内存，后端重启后失效；留空则使用后端 .env 配置。"}</p>
              <label className="mt-6 grid gap-2 text-sm font-medium">{"API Key"}<input autoFocus className="rounded-xl bg-white/70 px-4 py-3 font-normal outline-none ring-[#7342E2] transition focus:ring-2" onChange={(event) => setApiKey(event.target.value)} placeholder="sk-..." type="password" value={apiKey} /></label>
              <div className="mt-7 flex items-center justify-end gap-3"><button className="rounded-full px-5 py-2.5 text-sm font-semibold text-[#192837]/70 transition hover:bg-[#192837]/[0.08]" onClick={() => setApiKeyDialogOpen(false)} type="button">{"取消"}</button><button className="rounded-full bg-[#7342E2] px-5 py-2.5 text-sm font-semibold text-white shadow-[0_4px_20px_rgba(115,66,226,0.25)] transition hover:brightness-110" onClick={() => setApiKeyDialogOpen(false)} type="button">{"确认"}</button></div>
            </motion.section>
          </>
        ) : null}
      </AnimatePresence>
      <AnimatePresence>
        {clarification ? (
          <>
            <motion.button aria-label="关闭学习目标追问" className="fixed inset-0 z-50 bg-[#192837]/45 backdrop-blur-[5px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setClarification(null)} type="button" />
            <motion.section aria-label="细化学习目标" className="fixed left-1/2 top-1/2 z-[60] max-h-[calc(100dvh-48px)] w-[min(92vw,620px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[2rem] bg-[#F2F2EE] p-6 text-[#192837] shadow-[0_24px_80px_rgba(25,40,55,0.3)] sm:p-8" initial={reducedMotion ? false : { opacity: 0, y: 20, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 20, scale: 0.97 }} transition={{ duration: 0.32, ease }} role="dialog" aria-modal="true">
              <div className="flex items-start justify-between gap-5"><div><p className="text-xs font-semibold tracking-[0.12em] text-[#192837]/55">学习目标追问</p><h2 className="mt-2 font-[var(--font-heading)] text-3xl leading-tight">先把学习方向说清楚</h2></div><button aria-label="关闭" className="grid h-10 w-10 place-items-center rounded-full bg-[#192837]/[0.08]" onClick={() => setClarification(null)} type="button"><X size={20} strokeWidth={1.8} /></button></div>
              <p className="mt-5 rounded-2xl bg-[#7342E2]/10 p-4 text-sm leading-7 text-[#192837]/80">{clarification.reason}</p>
              <div className="mt-6 grid gap-6">{clarification.questions.map((item) => <fieldset className="grid gap-3" key={item.id}><legend className="text-base font-semibold">{item.label}</legend><p className="-mt-1 text-sm text-[#192837]/65">{item.helper}</p>{item.options ? <div className="flex flex-wrap gap-2">{item.options.map((option) => <button aria-pressed={clarificationAnswers[item.id] === option} className={`rounded-full px-4 py-2 text-sm font-semibold transition ${clarificationAnswers[item.id] === option ? "bg-[#7342E2] text-white" : "bg-[#192837]/[0.08] text-[#192837] hover:bg-[#192837]/[0.14]"}`} key={option} onClick={() => setClarificationAnswers((current) => ({ ...current, [item.id]: option }))} type="button">{option}</button>)}</div> : <textarea className="min-h-24 resize-y rounded-xl bg-white px-4 py-3 text-sm outline-none ring-[#7342E2] focus:ring-2" onChange={(event) => setClarificationAnswers((current) => ({ ...current, [item.id]: event.target.value }))} placeholder="请用一句话描述你希望完成的成果" value={clarificationAnswers[item.id] || ""} />}</fieldset>)}</div>
              <button className="mt-8 flex w-full items-center justify-between rounded-full bg-[#7342E2] px-6 py-4 font-semibold text-white shadow-[0_4px_24px_rgba(115,66,226,0.28)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50" disabled={clarification.questions.some((item) => !clarificationAnswers[item.id]?.trim())} onClick={confirmClarification} type="button">确认目标并生成资源<ArrowRightCircle size={20} /></button>
            </motion.section>
          </>
        ) : null}
      </AnimatePresence>
      <AnimatePresence>
        {workspaceOpen ? (
          <>
            <motion.button aria-label="关闭学习工作台" className="fixed inset-0 z-30 bg-[#192837]/35 backdrop-blur-[4px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setWorkspaceOpen(false)} type="button" />
            <motion.aside aria-label="学习工作台" className={`fixed bottom-0 right-0 top-0 z-40 flex flex-col overflow-y-auto bg-[#F2F2EE] px-6 pb-6 pt-24 text-[#192837] shadow-[-20px_0_70px_rgba(25,40,55,0.25)] transition-[width] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] sm:px-9 sm:pb-9 sm:pt-24 ${workspaceExpanded ? "w-full" : "w-[min(100%,600px)]"}`} initial={reducedMotion ? false : { x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} onScroll={(event) => setShowWorkspaceTopButton(event.currentTarget.scrollTop > 320)} ref={workspaceScrollRef} transition={{ duration: 0.42, ease }}>
              <div className={`flex items-start justify-between gap-5 ${workspaceExpanded ? "mx-auto w-full max-w-[1120px]" : ""}`}><div><p className="text-xs font-semibold tracking-[0.12em] text-[#192837]/55">学习工作台</p><h2 className="mt-2 font-[var(--font-heading)] text-3xl leading-tight">协同任务状态</h2></div><div className="flex items-center gap-2"><button aria-label={workspaceExpanded ? "收缩为侧边栏" : "全屏展开"} className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#192837]/[0.08] transition-transform hover:scale-105" onClick={() => setWorkspaceExpanded((expanded) => !expanded)} title={workspaceExpanded ? "收缩为侧边栏" : "全屏展开"} type="button">{workspaceExpanded ? <Minimize2 size={19} strokeWidth={1.8} /> : <Maximize2 size={19} strokeWidth={1.8} />}</button><button aria-label="关闭" className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#192837]/[0.08] transition-transform hover:scale-105" onClick={() => { setWorkspaceExpanded(false); setWorkspaceOpen(false); }} title="关闭工作台" type="button"><X size={20} strokeWidth={1.8} /></button></div></div>
               {workspaceExpanded ? <ExpandedWorkspaceLayout generationResult={generationResult} topic={topic} selectedResource={selectedResource} setSelectedResource={selectWorkspaceResource} activeStep={activeStep} setActiveStep={setActiveStep} selectedQualityGate={selectedQualityGate} setSelectedQualityGate={setSelectedQualityGate} onApplyRevision={applyRevision} onResolveQuiz={applyQuizAnswerKey} onGenerateAdaptiveQuiz={generateAdaptiveQuiz} quizAttempts={quizAttempts} onQuizAttemptChange={updateQuizAttempt} onExport={exportGeneratedResources} backendDemoMode={backendDemoMode} onOpenWorkflow={(index) => setWorkspaceDialog({ kind: "workflow", index })} onOpenQualityGate={(id) => setWorkspaceDialog({ kind: "quality", id })} /> : null}
               {resourceReady && generationResult ? (
                 <section className={`mt-7 rounded-2xl bg-[#192837] p-5 text-white shadow-[0_20px_50px_rgba(25,40,55,0.18)] sm:p-7 ${workspaceExpanded ? "hidden" : ""}`}>
                  <div className="mx-auto max-w-[80ch]">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <p className="text-xs font-semibold text-white/60">本次生成结果</p>
                        <h3 className="mt-2 text-xl font-semibold leading-tight">{topic}</h3>
                      </div>
                      <span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/90">{generationResult.mode === "demo" || backendDemoMode === true ? "本地演示" : "DeepSeek Chat"}</span>
                    </div>
                    {generationResult.diagnosis?.summary ? <p className="mt-4 max-w-[76ch] text-[0.96rem] leading-7 text-white/85">诊断：{generationResult.diagnosis.summary}</p> : null}
                    <div className="mt-6 flex flex-wrap gap-2" aria-label="资源类型">
                      {workspaceResourceItems(generationResult.resources ?? []).map((resource) => (
                        <button aria-pressed={selectedResource === resource.resource_type} className={`rounded-full px-4 py-2.5 text-sm font-semibold transition ${selectedResource === resource.resource_type ? "bg-white text-[#192837]" : "bg-white/15 text-white hover:bg-white/25"}`} key={resource.resource_type} onClick={() => setSelectedResource(resource.resource_type)} type="button">
                          {resourceLabel(resource.resource_type)}
                        </button>
                       ))}
                     </div>
                     {generationResult.generation_errors?.length ? <GenerationFailures key={generationSeq} errors={generationResult.generation_errors} onRegenerate={() => { void performGeneration(topic || learningGoal.trim()); }} /> : null}
                  </div>
                  <button className="mt-5 inline-flex items-center gap-2 rounded-full bg-white px-4 py-2.5 text-sm font-semibold text-[#192837] transition hover:bg-[#B99DFF]" onClick={exportGeneratedResources} type="button"><Download size={16} strokeWidth={1.9} />导出全部资源</button>
                  {selectedResource ? (() => {
                    const resources = generationResult.resources ?? [];
                    const resource = resources.find((item) => item.resource_type === selectedResource);
                    const resourceIndex = resources.findIndex((entry) => entry.resource_type === selectedResource);
                    const audit = generationResult.audit?.find((item) => item.resource_type === selectedResource || item.resource_index === resourceIndex);
                    const quizRounds = resource && isQuizResource(resource) ? resources.filter(isQuizResource) : [];
                    return resource ? (
                      <motion.article className="mx-auto mt-6 max-w-[80ch] rounded-2xl bg-[#102333] p-5 shadow-inner shadow-black/10 sm:p-7" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} key={selectedResource}>
                        <header className="flex flex-wrap items-start justify-between gap-4">
                          <div className="max-w-2xl">
                            <p className="text-xs font-semibold text-white/60">{isQuizResource(resource) ? `\u7b2c ${quizRoundNumber(resources, resource)} \u8f6e\u6d4b\u8bd5` : "资源预览"}</p>
                            <h4 className="mt-2 text-xl font-semibold leading-tight text-white">{resource.title}</h4>
                          </div>
                          {resource.estimated_duration_minutes ? <span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/80">预计 {resource.estimated_duration_minutes} 分钟</span> : null}
                        </header>
                        <RiskBanner level={resource.risk_level} />
                        {resource.robot_metadata ? <div className="mt-4 rounded-xl bg-white/[0.07] px-4 py-3 text-xs leading-6 text-white/70"><span className="font-semibold text-white/85">适配信息</span>　适配品牌：{resource.robot_metadata.brand || "未标注"} | 控制器版本：{resource.robot_metadata.controller_version || "未标注"} | 适用机型：{resource.robot_metadata.applicable_model || "未标注"}</div> : null}
                        <LookupChips instruction_links={resource.instruction_links} alarm_links={resource.alarm_links} />
                        <References citations={resource.citations} />
                        {resource.key_takeaways?.length ? (
                          <aside className="mt-6 rounded-xl bg-white/[0.07] p-4">
                            <p className="text-xs font-semibold text-white/60">学习重点</p>
                            <ul className="mt-3 grid gap-2 pl-5 text-sm leading-6 text-white/85 marker:text-[#B99DFF]">
                              {resource.key_takeaways.map((takeaway, index) => <li key={`${takeaway}-${index}`}>{takeaway}</li>)}
                            </ul>
                          </aside>
                        ) : null}
              {isQuizResource(resource) ? (
                <div className="mt-6 rounded-xl bg-white/[0.06] p-5 text-sm leading-7 text-white/75">
                  <p className="font-semibold text-white">答题说明</p>
                  <p className="mt-2">请完成每一道题后提交。提交前不会显示标准答案或解析。</p>
                </div>
              ) : (
                <div className="mt-6"><ResourceMarkdown content={resource.content || ""} /></div>
              )}
                        <LearningTools
                          onApplyRevision={applyRevision}
                          onGenerateAdaptiveQuiz={generateAdaptiveQuiz}
                          onQuizAttemptChange={updateQuizAttempt}
                          onResolveQuiz={applyQuizAnswerKey}
                          quizAttempt={quizAttempts[quizAttemptKey(resource)]}
                          resource={resource}
                          topic={topic}
                        />
                        {isQuizResource(resource) ? quizRounds.slice(1).map((roundResource) => {
                          const roundResourceIndex = resources.indexOf(roundResource);
                          const roundAudit = generationResult.audit?.find((item) => item.resource_type === roundResource.resource_type || item.resource_index === roundResourceIndex);
                          const roundNumber = quizRoundNumber(resources, roundResource);
                          return <section className="mt-8 border-t border-white/10 pt-7" key={roundResource.resource_id ?? roundResource.resource_type}>
                            <header className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold text-white/60">{`\u7b2c ${roundNumber} \u8f6e\u6d4b\u8bd5`}</p><h5 className="mt-2 text-lg font-semibold leading-tight text-white">{roundResource.title}</h5></div>{roundResource.estimated_duration_minutes ? <span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/80">预计 {roundResource.estimated_duration_minutes} 分钟</span> : null}</header>
                            {roundResource.key_takeaways?.length ? <aside className="mt-5 rounded-xl bg-white/[0.07] p-4"><p className="text-xs font-semibold text-white/60">学习重点</p><ul className="mt-3 grid gap-2 pl-5 text-sm leading-6 text-white/85 marker:text-[#B99DFF]">{roundResource.key_takeaways.map((takeaway, index) => <li key={`${takeaway}-${index}`}>{takeaway}</li>)}</ul></aside> : null}
                            <div className="mt-5 rounded-xl bg-white/[0.06] p-5 text-sm leading-7 text-white/75"><p className="font-semibold text-white">答题说明</p><p className="mt-2">请完成每一道题后提交。提交前不会显示标准答案或解析。</p></div>
                            <LearningTools
                              onApplyRevision={applyRevision}
                              onGenerateAdaptiveQuiz={generateAdaptiveQuiz}
                              onQuizAttemptChange={updateQuizAttempt}
                              onResolveQuiz={applyQuizAnswerKey}
                              quizAttempt={quizAttempts[quizAttemptKey(roundResource)]}
                              resource={roundResource}
                              topic={topic}
                            />
                            <footer className="mt-7 rounded-xl bg-white/[0.07] px-4 py-3 text-sm leading-6 text-white/80"><span className="font-semibold text-white">审核状态：</span>{auditVerdictLabel(roundAudit?.verdict)}{roundAudit?.issues?.[0]?.detail ? <span className="ml-2 text-white/65">{roundAudit.issues[0].detail}</span> : null}</footer>
                          </section>;
                        }) : null}
                        {isHandsOnResourceType(resource.resource_type) ? <p className="mt-7 text-xs leading-6 text-white/45">本内容仅作教学参考，实际操作请遵守现场安全管理规范与设备官方手册。</p> : null}
                        <footer className="mt-8 rounded-xl bg-white/[0.07] px-4 py-3 text-sm leading-6 text-white/80">
                          <span className="font-semibold text-white">审核状态：</span>{auditVerdictLabel(audit?.verdict)}
                          {audit?.issues?.[0]?.detail ? <span className="ml-2 text-white/65">{audit.issues[0].detail}</span> : null}
                        </footer>
                      </motion.article>
                    ) : null;
                  })() : null}
                </section>
              ) : null}
               <div className={`mt-8 grid gap-3 ${workspaceExpanded ? "hidden" : ""}`}>
                {workflowSteps.map((step, index) => (
                  <div key={step}>
                    <motion.button aria-expanded={activeStep === index} className="flex w-full items-center gap-4 rounded-2xl bg-white/65 p-4 text-left shadow-[0_8px_24px_rgba(25,40,55,0.05)]" onClick={() => setActiveStep(activeStep === index ? null : index)} type="button" whileHover={{ x: 4 }}>
                      <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full text-sm font-semibold ${activeStep === index ? "bg-[#7342E2] text-white" : "bg-[#192837]/[0.08]"}`}>0{index + 1}</span><span className="flex-1 font-semibold">{step}</span><span className="text-xs text-[#192837]/55">{activeStep === index ? "收起" : "查看"}</span>
                    </motion.button>
                    <AnimatePresence>
                      {activeStep === index ? <motion.div className="mt-2 rounded-2xl bg-[#192837]/[0.06] p-4 text-sm leading-6 text-[#192837]/80" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}>
                        {index === 0 ? <><p className="font-semibold text-[#192837]">学情诊断</p><p className="mt-2">{generationResult?.diagnosis?.summary || "暂无诊断结果。请先生成学习资源。"}</p><div className="mt-3 flex flex-wrap gap-2"><span className="rounded-full bg-white/70 px-3 py-1 text-xs">学习风格：{generationResult?.diagnosis?.learning_style || "未返回"}</span><span className="rounded-full bg-white/70 px-3 py-1 text-xs">建议难度：{generationResult?.diagnosis?.recommended_difficulty || "未返回"}</span></div>{generationResult?.diagnosis?.skill_gaps?.length ? <div className="mt-3"><SkillGapCards gaps={generationResult.diagnosis.skill_gaps} /></div> : null}</> : null}
                        {index === 1 ? <><p className="font-semibold text-[#192837]">知识生成</p><p className="mt-2">已返回 {generationResult?.resources?.length ?? 0} 种资源。点击上方资源标签可查看完整正文。</p></> : null}
                        {index === 2 ? <><p className="font-semibold text-[#192837]">内容审核</p><p className="mt-2">{generationResult?.audit?.length ? generationResult.audit.map((audit) => `${resourceLabel(audit.resource_type || "")}: ${audit.verdict || "未返回"}`).join("；") : "暂无审核结果。"}</p></> : null}
                      </motion.div> : null}
                    </AnimatePresence>
                  </div>
                ))}
              </div>
              <div className="mt-8 rounded-2xl bg-[#192837] p-6 text-white"><p className="text-xs font-semibold text-white/55">质量闸门</p><div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs font-semibold">{qualityGates.map((gate) => <button aria-pressed={selectedQualityGate === gate.id} className={`rounded-xl px-2 py-3 transition ${selectedQualityGate === gate.id ? "bg-white text-[#192837]" : "bg-white/10 text-white hover:bg-white/20"}`} key={gate.id} onClick={() => setSelectedQualityGate(gate.id)} type="button">{gate.label}</button>)}</div><AnimatePresence mode="wait"><motion.div className="mt-4 rounded-xl bg-white/10 p-4 text-sm leading-6 text-white/80" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} key={selectedQualityGate}>{selectedQualityGate === "evidence" ? <><p className="font-semibold text-white">依据校验</p><p className="mt-1">{generationResult?.audit?.length ? "以下为每种资源的审核结论。" : "生成后将展示每种资源的审核结论。"}</p>{generationResult?.audit?.length ? <ul className="mt-2 grid gap-1 text-xs">{generationResult.audit.map((audit, index) => <li key={`${audit.resource_type}-${index}`}>{resourceLabel(audit.resource_type || "资源")}：{audit.verdict || "未返回结论"}{audit.issues?.[0]?.detail ? `，${audit.issues[0].detail}` : ""}</li>)}</ul> : null}</> : null}{selectedQualityGate === "difficulty" ? <><p className="font-semibold text-white">难度匹配</p><p className="mt-1">建议难度：{generationResult?.diagnosis?.recommended_difficulty || "等待学情诊断"}</p>{generationResult?.resources?.length ? <ul className="mt-2 grid gap-1 text-xs">{generationResult.resources.map((resource, index) => <li key={`${resource.resource_type}-${index}`}>{resourceLabel(resource.resource_type)}：{resource.difficulty_level || "未返回难度"}</li>)}</ul> : <p className="mt-1 text-xs text-white/65">生成资源后将比较资源难度与学情诊断。</p>}</> : null}{selectedQualityGate === "expression" ? <><p className="font-semibold text-white">表达审核</p><p className="mt-1">{generationResult?.audit?.some((audit) => audit.issues?.length) ? "存在需要关注的表达或内容问题，请查看下方审核意见。" : generationResult ? "未返回额外表达问题，当前资源通过审核。" : "生成后将展示表达审核意见。"}</p>{generationResult?.audit?.flatMap((audit) => audit.issues ?? []).length ? <ul className="mt-2 grid gap-1 text-xs">{generationResult.audit.flatMap((audit) => audit.issues ?? []).map((issue, index) => <li key={`${issue.detail}-${index}`}>{issue.detail || "未提供具体问题"}</li>)}</ul> : null}</> : null}</motion.div></AnimatePresence></div>
            </motion.aside>
            <AnimatePresence>
              {workspaceDialog ? (
                <>
                  <motion.button aria-label="关闭详情弹窗" className="fixed inset-0 z-[60] bg-[#192837]/45 backdrop-blur-[5px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setWorkspaceDialog(null)} type="button" />
                  <motion.section aria-label="工作流详情" className="fixed left-1/2 top-1/2 z-[70] max-h-[min(760px,calc(100dvh-64px))] w-[min(92vw,680px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[1.75rem] bg-[#F2F2EE] p-6 text-[#192837] shadow-[0_24px_80px_rgba(25,40,55,0.3)] sm:p-8" initial={reducedMotion ? false : { opacity: 0, y: 20, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 20, scale: 0.97 }} transition={{ duration: 0.32, ease }} role="dialog" aria-modal="true">
                    <div className="flex items-start justify-between gap-5">
                      <div>
                        <p className="text-xs font-semibold tracking-[0.14em] text-[#192837]/55">{workspaceDialog.kind === "workflow" ? "协同工作流" : "质量闸门"}</p>
                        <h3 className="mt-2 font-[var(--font-heading)] text-2xl leading-tight">{workspaceDialog.kind === "workflow" ? workflowSteps[workspaceDialog.index] : qualityGates.find((gate) => gate.id === workspaceDialog.id)?.label}</h3>
                      </div>
                      <button aria-label="关闭详情" className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#192837]/[0.08] transition-transform hover:scale-105" onClick={() => setWorkspaceDialog(null)} type="button"><X size={19} strokeWidth={1.8} /></button>
                    </div>
                    <div className="mt-6 rounded-2xl bg-[#192837] p-5 text-white sm:p-6">
                      {workspaceDialog.kind === "workflow" && workspaceDialog.index === 0 ? <><p className="text-sm font-semibold text-white/60">学习画像诊断</p><p className="mt-3 text-sm leading-7 text-white/85">{generationResult?.diagnosis?.summary || "生成资源后将展示学习目标、基础能力和知识缺口诊断。"}</p>{generationResult?.diagnosis?.skill_gaps?.length ? <div className="mt-5"><SkillGapCards gaps={generationResult.diagnosis.skill_gaps} dark /></div> : null}<LearningPathMap groups={buildLearningPath(coreMap, generationResult?.diagnosis?.skill_gaps)} /></> : null}
                      {workspaceDialog.kind === "workflow" && workspaceDialog.index === 1 ? <><p className="text-sm font-semibold text-white/60">RAG 知识生成</p><p className="mt-3 text-sm leading-7 text-white/85">根据学习画像检索知识库，生成与当前目标匹配的学习资源。本次已生成 {generationResult?.resources?.length ?? 0} 类资源。</p><div className="mt-5 grid gap-2 sm:grid-cols-3">{(generationResult?.resources ?? []).map((item) => <div className="rounded-xl bg-white/[0.08] px-4 py-3 text-sm text-white/85" key={item.resource_type}>{resourceLabel(item.resource_type)}<span className="mt-1 block text-xs text-white/55">{item.difficulty_level || "待评估难度"}</span></div>)}</div></> : null}
                      {workspaceDialog.kind === "workflow" && workspaceDialog.index === 2 ? <><p className="text-sm font-semibold text-white/60">内容审核与保真修正</p><p className="mt-3 text-sm leading-7 text-white/85">逐项检查资源的知识依据、难度匹配和表达质量，并保留需要修正的具体问题。</p><ul className="mt-5 grid gap-2 text-sm text-white/80">{(generationResult?.audit ?? []).map((item, index) => <li className="flex items-center justify-between gap-4 rounded-xl bg-white/[0.08] px-4 py-3" key={`dialog-audit-${index}`}><span>{resourceLabel(item.resource_type || "资源")}</span><span className="text-white/60">{auditVerdictLabel(item.verdict)}</span></li>)}</ul></> : null}
                      {workspaceDialog.kind === "quality" && workspaceDialog.id === "evidence" ? <><p className="text-sm font-semibold text-white/60">依据校验</p><p className="mt-3 text-sm leading-7 text-white/85">检查生成内容是否有知识库依据，并显示每种资源对应的审核结论。</p><ul className="mt-5 grid gap-2 text-sm text-white/80">{(generationResult?.audit ?? []).map((item, index) => <li className="rounded-xl bg-white/[0.08] px-4 py-3" key={`dialog-evidence-${index}`}><span>{resourceLabel(item.resource_type || "资源")}</span><span className="ml-3 text-white/60">{auditVerdictLabel(item.verdict)}</span>{item.issues?.[0]?.detail ? <span className="mt-1 block text-xs text-white/55">{item.issues[0].detail}</span> : null}</li>)}</ul></> : null}
                      {workspaceDialog.kind === "quality" && workspaceDialog.id === "difficulty" ? <><p className="text-sm font-semibold text-white/60">难度匹配</p><p className="mt-3 text-sm leading-7 text-white/85">当前建议难度：{generationResult?.diagnosis?.recommended_difficulty || "等待学情诊断"}。系统会将资源难度与学习基础和目标进行比对。</p></> : null}
                      {workspaceDialog.kind === "quality" && workspaceDialog.id === "expression" ? <><p className="text-sm font-semibold text-white/60">表达审核</p><p className="mt-3 text-sm leading-7 text-white/85">{generationResult?.audit?.some((item) => item.issues?.length) ? "部分内容需要进一步修正，请结合下方审核问题检查表达、结构和可用性。" : "当前资源通过表达质量检查，结构清晰，适合继续学习。"}</p>{generationResult?.audit?.flatMap((item) => item.issues ?? []).length ? <ul className="mt-5 grid gap-2 text-sm text-white/80">{generationResult.audit.flatMap((item) => item.issues ?? []).map((issue, index) => <li className="rounded-xl bg-white/[0.08] px-4 py-3" key={`dialog-issue-${index}`}>{issue.detail || "待补充审核说明"}</li>)}</ul> : null}</> : null}
                    </div>
                  </motion.section>
                </>
              ) : null}
            </AnimatePresence>
            <AnimatePresence>
              {safetyAckResource ? (
                <>
                  <motion.div className="fixed inset-0 z-[75] bg-[#192837]/50 backdrop-blur-[6px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
                  <motion.section aria-label="安全确认" className="fixed left-1/2 top-1/2 z-[80] w-[min(92vw,460px)] -translate-x-1/2 -translate-y-1/2 rounded-[1.75rem] bg-[#F2F2EE] p-6 text-[#192837] shadow-[0_24px_80px_rgba(25,40,55,0.3)] sm:p-7" initial={reducedMotion ? false : { opacity: 0, y: 20, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 20, scale: 0.97 }} transition={{ duration: 0.32, ease }} role="dialog" aria-modal="true">
                    <div className="flex items-start gap-3">
                      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-red-400/15 text-xl">⚠️</span>
                      <div>
                        <h3 className="font-[var(--font-heading)] text-xl leading-tight">安全确认</h3>
                        <p className="mt-2 text-sm leading-7 text-[#192837]/75">本课程涉及工业机器人实操操作，存在机械伤害风险，请确认已接受基础安全培训并遵守现场操作规程。</p>
                      </div>
                    </div>
                    <label className="mt-5 flex cursor-pointer items-center gap-3 rounded-2xl border border-[#192837]/10 bg-white px-4 py-3">
                      <input checked={safetyAckChecked} className="h-4 w-4 accent-[#7342E2]" onChange={(event) => setSafetyAckChecked(event.target.checked)} type="checkbox" />
                      <span className="text-sm font-medium">我已了解风险并遵守安全规范</span>
                    </label>
                    <button className="mt-5 w-full rounded-full bg-[#192837] px-4 py-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40" disabled={!safetyAckChecked} onClick={confirmSafetyAck} type="button">确认进入</button>
                  </motion.section>
                </>
              ) : null}
            </AnimatePresence>
            <AnimatePresence>
              {showWorkspaceTopButton ? (
                <motion.button aria-label="返回工作台顶部" className="fixed bottom-7 right-7 z-50 grid h-11 w-11 place-items-center rounded-full bg-[#192837] text-white shadow-[0_10px_30px_rgba(25,40,55,0.28)] transition-transform hover:scale-105" initial={reducedMotion ? false : { opacity: 0, y: 12, scale: 0.9 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 12, scale: 0.9 }} onClick={scrollWorkspaceToTop} title="返回顶部" type="button" whileTap={{ scale: 0.94 }}>
                  <ArrowUp size={20} strokeWidth={2} />
                </motion.button>
              ) : null}
            </AnimatePresence>
          </>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
