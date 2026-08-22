import { AnimatePresence, motion, useMotionValue, useReducedMotion, useSpring, useTransform } from "framer-motion";
import { ArrowRightCircle, ArrowUp, BrainCircuit, Database, Maximize2, Menu, Minimize2, RefreshCw, ShieldCheck, Sparkles, Upload, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from "react";
import { assessLearningGoal, askStudyQuestion, createDemoQuiz, refineLearningGoal, submitQuiz, type ClarificationQuestion, type LearnerQuestionResponse, type Quiz, type QuizSubmissionResult } from "./learning-session";
import { initialWorkflowEvents, mergeWorkflowEvent, simulateWorkflow, subscribeWorkflow, workflowStages, type WorkflowEvent } from "./workflow-stream";

type Variant = "a" | "b";

const navigation = ["系统概览", "学习诊断", "知识生成", "审核修正", "学习工作台"];
const workflowSteps = ["学情诊断", "知识生成", "内容审核"];
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
const resourceOptions = [
  { id: "lecture", label: "讲义" },
  { id: "guide", label: "实操指南" },
  { id: "quiz", label: "测试题" },
];

type GeneratedResource = {
  resource_type: string;
  title: string;
  content?: string;
  difficulty_level?: string;
  estimated_duration_minutes?: number;
  key_takeaways?: string[];
  quiz?: Quiz;
};

type GenerationResult = {
  task_id?: string;
  status?: string;
  diagnosis?: { summary?: string; learning_style?: string; recommended_difficulty?: string; skill_gaps?: Array<{ topic?: string; priority?: string }> };
  resources?: GeneratedResource[];
  audit?: Array<{ resource_index?: number; resource_type?: string; verdict?: string; issues?: Array<{ detail?: string }> }>;
  agent_log?: Array<{ agent?: string; status?: string }>;
  mode?: "demo" | "api";
};

const resourceLabel = (type: string) => resourceOptions.find((option) => option.id === type)?.label ?? type;
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

function ResourceMarkdown({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
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

function KnowledgeManager({ open, onClose }: { open: boolean; onClose: () => void }) {
  const reducedMotion = useReducedMotion();
  const [stats, setStats] = useState<{ mode?: string; total_documents?: number; total_chunks?: number } | null>(null);
  const [docId, setDocId] = useState("");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadStats = async () => {
    try {
      const response = await fetch("http://localhost:8000/api/knowledge/stats");
      if (!response.ok) throw new Error(`API ${response.status}`);
      setStats(await response.json());
    } catch {
      setStats(null);
    }
  };

  useEffect(() => {
    if (open) loadStats();
  }, [open]);

  const runImport = async () => {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const response = await fetch("http://localhost:8000/api/knowledge/import", { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `API ${response.status}`);
      setMessage(`批量导入完成：${data.imported ?? 0}/${data.total ?? 0} 篇`);
      loadStats();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const submitUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    setError(null);
    const id = docId.trim() || `doc_${Date.now()}`;
    try {
      const response = await fetch("http://localhost:8000/api/knowledge/upload", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_id: id, title: title.trim(), content }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `API ${response.status}`);
      setMessage(`已上传「${data.title}」，切分为 ${data.chunks_count} 个片段`);
      setDocId("");
      setTitle("");
      setContent("");
      loadStats();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.button aria-label="关闭知识库管理" className="fixed inset-0 z-30 bg-[#192837]/35 backdrop-blur-[4px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} type="button" />
          <motion.section aria-label="知识库管理" className="fixed inset-x-3 bottom-3 top-3 z-40 mx-auto max-w-[760px] overflow-y-auto rounded-[2rem] bg-[#F2F2EE] p-6 text-[#192837] shadow-[0_22px_72px_rgba(25,40,55,0.28)] sm:inset-x-auto sm:bottom-auto sm:right-8 sm:top-1/2 sm:max-h-[calc(100dvh-48px)] sm:w-[min(720px,calc(100vw-64px))] sm:-translate-y-1/2 sm:p-8" initial={reducedMotion ? false : { opacity: 0, y: 28 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 28 }} transition={{ duration: 0.35, ease }} role="dialog" aria-modal="true">
            <div className="flex items-start justify-between gap-5">
              <div><p className="text-xs font-semibold tracking-[0.12em] text-[#192837]/55">知识库管理</p><h2 className="mt-2 font-[var(--font-heading)] text-3xl leading-tight">导入知识文档</h2></div>
              <button aria-label="关闭" className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#192837]/[0.08]" onClick={onClose} type="button"><X size={20} strokeWidth={1.8} /></button>
            </div>

            <div className="mt-6 flex items-center gap-4 rounded-2xl bg-[#192837] p-5 text-white">
              <Database className="shrink-0" color="#B99DFF" size={28} strokeWidth={1.8} />
              <div className="flex-1">
                <p className="text-xs font-semibold text-white/55">当前知识库</p>
                <p className="mt-1 text-lg font-semibold">{stats ? `${stats.total_documents ?? 0} 篇文档 · ${stats.total_chunks ?? 0} 个片段` : "无法连接后端"}</p>
              </div>
              <button className="rounded-full bg-white/10 px-4 py-2 text-xs font-semibold hover:bg-white/20" onClick={loadStats} type="button"><RefreshCw size={14} strokeWidth={1.8} className="mr-1 inline -translate-y-px" />刷新</button>
            </div>

            <div className="mt-5 rounded-2xl bg-white/60 p-5">
              <p className="font-semibold">批量导入 data/raw</p>
              <p className="mt-1 text-sm text-[#192837]/70">把 data/raw/ 目录下所有 .md 文件向量化导入知识库（重复导入安全）。</p>
              <button className="mt-4 flex items-center gap-2 rounded-full bg-[#7342E2] px-5 py-2.5 text-sm font-semibold text-white shadow-[0_4px_24px_rgba(115,66,226,0.28)] disabled:cursor-wait disabled:opacity-60" disabled={busy} onClick={runImport} type="button"><Upload size={16} strokeWidth={1.8} />{busy ? "导入中..." : "执行批量导入"}</button>
            </div>

            <form className="mt-5 grid gap-4 rounded-2xl bg-white/60 p-5" onSubmit={submitUpload}>
              <p className="font-semibold">上传单篇文档</p>
              <label className="grid gap-2 text-sm font-medium">标题<input className="rounded-xl bg-white/70 px-3 py-3 font-normal outline-none ring-[#7342E2] transition focus:ring-2" onChange={(event) => setTitle(event.target.value)} placeholder="例如：FANUC 坐标系偏移设置" required value={title} /></label>
              <label className="grid gap-2 text-sm font-medium">文档标识（选填，留空自动生成）<input className="rounded-xl bg-white/70 px-3 py-3 font-normal outline-none ring-[#7342E2] transition focus:ring-2" onChange={(event) => setDocId(event.target.value)} placeholder="例如：k1_coord_offset_001" value={docId} /></label>
              <label className="grid gap-2 text-sm font-medium">正文（Markdown）<textarea className="min-h-40 resize-y rounded-xl bg-white/70 px-3 py-3 font-normal outline-none ring-[#7342E2] transition focus:ring-2" onChange={(event) => setContent(event.target.value)} placeholder="# 标题&#10;&#10;正文内容..." required value={content} /></label>
              {message ? <p className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</p> : null}
              {error ? <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
              <button className="flex items-center justify-center gap-2 rounded-full bg-[#192837] px-5 py-3 text-sm font-semibold text-white disabled:cursor-wait disabled:opacity-60" disabled={busy} type="submit">{busy ? "上传中..." : "上传到知识库"}</button>
            </form>
          </motion.section>
        </>
      ) : null}
    </AnimatePresence>
  );
}

function LearningTools({ resource, topic, onApplyRevision }: { resource: GeneratedResource; topic: string; onApplyRevision: (resourceType: string, response: LearnerQuestionResponse) => void }) {
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
  const quiz = resource.quiz || (resource.resource_type === "quiz" ? createDemoQuiz(topic) : null);
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
        {submitted && quizResult?.learning_advice?.length ? <ul className="mt-4 grid gap-2 rounded-xl bg-[#B99DFF]/10 p-4 text-sm leading-6 text-[#EDE8FF]">{quizResult.learning_advice.map((advice) => <li key={advice}>- {advice}</li>)}</ul> : null}
      </div> : null}
    </section>
  );
}

function WorkflowProgress({ events, mode }: { events: WorkflowEvent[]; mode: "idle" | "waiting" | "connected" | "demo" | "complete" }) {
  const modeLabel = mode === "connected" ? "实时连接中" : mode === "demo" ? "演示流程" : mode === "waiting" ? "等待任务响应" : mode === "complete" ? "任务已完成" : "尚未开始";
  return (
    <section className="rounded-2xl bg-[#0B1D2A] p-5 text-white" aria-label="Agent 实时工作状态">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold tracking-[0.12em] text-white/55">Agent 工作状态</p><h5 className="mt-2 text-lg font-semibold">协同工作流</h5></div><span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/75">{modeLabel}</span></div>
      <ol className="mt-5 grid gap-2">{workflowStages.map((stage, index) => { const event = events.find((item) => item.agent === stage.agent); const status = event?.status || "pending"; const color = status === "done" ? "bg-emerald-400" : status === "running" ? "bg-[#B99DFF] animate-pulse" : status === "error" ? "bg-red-400" : "bg-white/25"; const label = status === "done" ? "已完成" : status === "running" ? "进行中" : status === "error" ? "异常" : "等待中"; return <li className="flex items-center gap-3 rounded-xl bg-white/[0.06] px-3 py-3 text-sm" key={stage.agent}><span className={`h-2.5 w-2.5 shrink-0 rounded-full ${color}`} /><span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-white/10 text-[11px]">0{index + 1}</span><span className="flex-1 font-semibold">{stage.label}</span><span className="text-xs text-white/60">{event?.message || label}</span></li>; })}</ol>
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
}) {
  const resource = generationResult?.resources?.find((item) => item.resource_type === selectedResource);
  const resourceIndex = generationResult?.resources?.findIndex((item) => item.resource_type === selectedResource);
  const audit = generationResult?.audit?.find((item) => item.resource_type === selectedResource || item.resource_index === resourceIndex);
  const workflowDetail = "详情已在弹窗中打开。";
  return (
    <div className="workspace-expanded-content mt-8 grid min-h-[calc(100dvh-150px)] min-w-0 w-full max-w-none grid-cols-[230px_minmax(0,1fr)] gap-8 rounded-[2rem] bg-[#192837] p-5 text-white shadow-[0_24px_70px_rgba(25,40,55,0.2)] sm:p-7 lg:grid-cols-[260px_minmax(0,1fr)] lg:gap-10">
      <nav aria-label="学习工作台目录" className="self-start lg:sticky lg:top-7">
        <div className="rounded-2xl bg-white/[0.07] p-4">
          <p className="text-xs font-semibold tracking-[0.14em] text-white/55">资源目录</p>
          <div className="mt-4 grid gap-2">
            {(generationResult?.resources ?? []).map((item, index) => <button aria-current={selectedResource === item.resource_type ? "page" : undefined} className={`flex items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-semibold transition ${selectedResource === item.resource_type ? "bg-[#7342E2] text-white shadow-[0_8px_20px_rgba(115,66,226,0.28)]" : "bg-white/[0.06] text-white/75 hover:bg-white/12 hover:text-white"}`} key={item.resource_type} onClick={() => setSelectedResource(item.resource_type)} type="button"><span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-white/15 text-[11px]">0{index + 1}</span><span className="truncate">{resourceLabel(item.resource_type)}</span></button>)}
            {!generationResult?.resources?.length ? <p className="px-3 py-2 text-sm leading-6 text-white/55">生成资源后显示目录</p> : null}
          </div>
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
          <span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/85">{generationResult?.mode === "demo" ? "本地演示" : "DeepSeek Chat"}</span>
        </div>
        {generationResult?.diagnosis?.summary ? <p className="mt-5 max-w-[78ch] text-base leading-8 text-white/80">诊断：{generationResult.diagnosis.summary}</p> : null}

        {resource ? <motion.article className="mt-7 rounded-2xl bg-[#102333] p-6 shadow-inner shadow-black/10 sm:p-8 lg:p-10" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} key={selectedResource}>
          <header className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold text-white/55">资源预览</p><h4 className="mt-2 text-2xl font-semibold leading-tight text-white">{resource.title}</h4></div>{resource.estimated_duration_minutes ? <span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/75">预计 {resource.estimated_duration_minutes} 分钟</span> : null}</header>
          {resource.key_takeaways?.length ? <aside className="mt-7 rounded-xl bg-white/[0.07] p-5"><p className="text-xs font-semibold text-white/60">学习重点</p><ul className="mt-3 grid gap-2 pl-5 text-sm leading-7 text-white/85 marker:text-[#B99DFF]">{resource.key_takeaways.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></aside> : null}
          <div className="mt-8"><ResourceMarkdown content={resource.content || ""} /></div>
          <LearningTools onApplyRevision={onApplyRevision} resource={resource} topic={topic} />
          <footer className="mt-9 rounded-xl bg-white/[0.07] px-5 py-4 text-sm leading-7 text-white/75"><span className="font-semibold text-white">审核状态：</span>{auditVerdictLabel(audit?.verdict)}{audit?.issues?.[0]?.detail ? <span className="ml-2">{audit.issues[0].detail}</span> : null}</footer>
        </motion.article> : <div className="mt-7 rounded-2xl bg-[#102333] p-8 text-white/65">选择左侧资源目录查看内容。</div>}

        {activeStep !== null ? <motion.section className="mt-6 rounded-2xl bg-white/[0.08] p-6" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} key={`workflow-${activeStep}`}><p className="text-xs font-semibold tracking-[0.14em] text-white/55">工作流详情</p><h4 className="mt-2 text-xl font-semibold text-white">{workflowSteps[activeStep]}</h4><p className="mt-3 text-sm leading-7 text-white/75">{workflowDetail}</p></motion.section> : null}
        <motion.section className="mt-6 rounded-2xl bg-white/[0.08] p-6" layout><p className="text-xs font-semibold tracking-[0.14em] text-white/55">质量闸门详情</p><h4 className="mt-2 text-xl font-semibold text-white">{qualityGates.find((gate) => gate.id === selectedQualityGate)?.label}</h4><p className="mt-3 text-sm leading-7 text-white/75">{selectedQualityGate === "evidence" ? "查看每种资源是否有知识库依据和审核结论。" : selectedQualityGate === "difficulty" ? `建议难度：${generationResult?.diagnosis?.recommended_difficulty || "等待学情诊断"}` : "查看资源的表达质量、结构完整性和可用性。"}</p></motion.section>
      </main>
    </div>
  );
}

function MobileMenu({ open, onClose, onNavigate, onOpenGenerator, onOpenWorkspace, onOpenKb }: { open: boolean; onClose: () => void; onNavigate: (index: number) => void; onOpenGenerator: () => void; onOpenWorkspace: () => void; onOpenKb: () => void }) {
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
            <div className="mt-auto grid gap-3"><ActionButton kind="accent" onClick={onOpenGenerator}>生成学习资源</ActionButton><ActionButton kind="quiet" onClick={onOpenWorkspace}>进入工作台</ActionButton><ActionButton kind="quiet" onClick={onOpenKb}>知识库管理</ActionButton></div>
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
  const [kbOpen, setKbOpen] = useState(false);
  const [workspaceExpanded, setWorkspaceExpanded] = useState(false);
  const [selectedQualityGate, setSelectedQualityGate] = useState<QualityGate | null>("evidence");
  const [workspaceDialog, setWorkspaceDialog] = useState<WorkspaceDialog | null>(null);
  const [topic, setTopic] = useState("");
  const [resourceTypes, setResourceTypes] = useState<string[]>(["lecture"]);
  const [resourceReady, setResourceReady] = useState(false);
  const [selectedResource, setSelectedResource] = useState<string | null>(null);
  const [generationResult, setGenerationResult] = useState<GenerationResult | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationProgressOpen, setGenerationProgressOpen] = useState(false);
  const [workflowEvents, setWorkflowEvents] = useState<WorkflowEvent[]>(initialWorkflowEvents);
  const [workflowMode, setWorkflowMode] = useState<"idle" | "waiting" | "connected" | "demo" | "complete">("idle");
  const [learningGoal, setLearningGoal] = useState("");
  const [confirmedGoal, setConfirmedGoal] = useState<string | null>(null);
  const [clarification, setClarification] = useState<{ reason: string; questions: ClarificationQuestion[] } | null>(null);
  const [clarificationAnswers, setClarificationAnswers] = useState<Record<string, string>>({});
  const [education, setEducation] = useState("本科");
  const [major, setMajor] = useState("");
  const [skills, setSkills] = useState("");
  const [workYears, setWorkYears] = useState(1);
  const [industry, setIndustry] = useState("");
  const [role, setRole] = useState("");
  const [demoMode, setDemoMode] = useState(false);
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
  useEffect(() => () => stopWorkflowRef.current?.(), []);
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
        key_takeaways: [...(resource.key_takeaways ?? []), "已根据你的学习疑问补充说明"],
        };
      }),
    } : current);
  };
  const confirmClarification = () => {
    const refined = refineLearningGoal(learningGoal, clarificationAnswers);
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
      const response = await fetch("http://localhost:8000/api/generate", {
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
        resources: resourceTypes.map((type) => ({ resource_type: type, title: `${resourceLabel(type)}：${learningGoal}`, content: `# ${learningGoal}\n\n这是 XH-agent 本地演示资源。启动后端后将由 Agent 1 学情诊断、Agent 2 知识生成、Agent 3 内容审核返回真实内容。`, difficulty_level: "beginner", estimated_duration_minutes: type === "quiz" ? 15 : 30 })),
        audit: resourceTypes.map((type, index) => ({ resource_index: index, resource_type: type, verdict: "approved" })),
        agent_log: [{ agent: "diagnosis", status: "done" }, { agent: "generation", status: "done" }, { agent: "audit", status: "done" }],
      };
    }
    if (result.mode === "api") {
      setWorkflowEvents((current) => (result.agent_log ?? []).reduce((events, item) => mergeWorkflowEvent(events, { agent: item.agent || "generation", status: item.status === "error" ? "error" : "done", message: item.status === "error" ? "异常" : "已完成" }), current));
      if (result.status === "completed") setWorkflowMode("complete");
    }
    setGenerationResult(result);
    setResourceReady(true);
    setSelectedResource(result.resources?.[0]?.resource_type ?? resourceTypes[0] ?? null);
    setIsGenerating(false);
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    setGenerationProgressOpen(false);
    setGeneratorOpen(false);
    setWorkspaceOpen(true);
  };
  const submitGeneration = async (event: FormEvent<HTMLFormElement>) => {
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

    const apiBase = window.localStorage.getItem("xh-agent-api-base") || "http://localhost:8000";
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
        resources: resourceTypes.map((type) => ({ resource_type: type, title: `${resourceLabel(type)}：${learningGoal}`, content: `# ${learningGoal}\n\n这是 XH-agent 的本地演示资源。连接后端后会显示真实 Agent 生成内容。`, difficulty_level: "beginner", estimated_duration_minutes: type === "quiz" ? 15 : 30 })),
        audit: resourceTypes.map((type, index) => ({ resource_index: index, resource_type: type, verdict: "approved" })),
        agent_log: workflowStages.map((stage) => ({ agent: stage.agent, status: "done" })),
      };
    }

    setWorkflowEvents((current) => (result.agent_log ?? []).reduce(
      (events, item) => mergeWorkflowEvent(events, {
        agent: item.agent || "generation",
        status: item.status === "error" ? "error" : "done",
        message: item.status === "error" ? "执行失败" : "已完成",
      }),
      current,
    ));
    setWorkflowMode("complete");
    setGenerationResult(result);
    setResourceReady(true);
    setSelectedResource(result.resources?.[0]?.resource_type ?? resourceTypes[0] ?? null);
    setIsGenerating(false);
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    setGenerationProgressOpen(false);
    setWorkspaceOpen(true);
  };
  const toggleResourceType = (item: string) => {
    setResourceTypes((current) => current.includes(item) ? (current.length === 1 ? current : current.filter((type) => type !== item)) : [...current, item]);
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

      <header className="relative z-10 mx-auto flex max-w-[1280px] items-center justify-between px-5 py-4 sm:px-8 sm:py-5">
        {!schemeB ? <BrandMark /> : null}
        <nav className={`hidden items-center gap-7 md:flex ${schemeB ? "absolute left-1/2 -translate-x-1/2" : ""}`} aria-label="Primary navigation">
          {navigation.map((item, index) => <button className={`text-sm font-medium transition-opacity hover:opacity-50 ${activePanel === panelIds[index] ? "opacity-100" : "opacity-65"}`} key={item} onClick={() => selectPanel(index)} type="button">{item}</button>)}
        </nav>
        <div className="hidden items-center gap-2 md:flex"><ActionButton kind="accent" onClick={openGenerator}>生成学习资源</ActionButton><ActionButton kind="quiet" onClick={() => setWorkspaceOpen(true)}>进入工作台</ActionButton><ActionButton kind="quiet" onClick={() => setKbOpen(true)}>知识库</ActionButton></div>
        <button aria-expanded={menuOpen} aria-label="打开菜单" className="grid h-10 w-10 place-items-center rounded-full bg-[#F2F2EE]/85 md:hidden" onClick={() => setMenuOpen(true)}><Menu size={21} strokeWidth={1.8} /></button>
      </header>

      <div className={`relative z-10 mx-auto max-w-[1280px] px-5 sm:px-8 ${schemeB ? "lg:flex lg:items-end lg:justify-start lg:gap-6" : ""}`} style={{ paddingTop: "clamp(40px, 8vw, 72px)" }}>
        <motion.div className={schemeB ? "max-w-[560px] rounded-[2rem] bg-[#F2F2EE]/78 p-7 shadow-[0_18px_60px_rgba(25,40,55,0.10)] backdrop-blur-[3px] sm:p-10" : "max-w-[560px]"} style={reducedMotion ? undefined : { x: mainX, y: mainY }}>
          <motion.h1 {...fadeUp(0)} className="mb-6 font-[var(--font-heading)] text-[clamp(1.65rem,5vw,3rem)] font-bold leading-[1.05] tracking-[-0.01em]">
            <BrainCircuit className="relative -top-0.5 mr-1 inline-block align-middle" color="#192837" size={24} strokeWidth={1.9} />
            从学习画像开始 <Sparkles className="relative -top-0.5 mx-1 inline-block align-middle" color="#192837" size={24} strokeWidth={1.9} /> 生成可信的个性化内容 <ShieldCheck className="relative -top-0.5 ml-1 inline-block align-middle" color="#192837" size={24} strokeWidth={1.9} />
          </motion.h1>
          <motion.p {...fadeUp(1)} className="max-w-[560px] text-[clamp(0.9rem,2.5vw,1.1rem)] leading-[1.65] opacity-80">XH-Agent 通过 4 个 Agent、3 道质量闸门和 32 篇知识库文档，完成学情诊断、RAG 约束生成、内容审核与保真修正。</motion.p>
          <motion.button {...fadeUp(2)} className="mt-8 flex min-w-[210px] max-w-max items-center justify-between gap-8 rounded-[50px] bg-[#7342E2] px-6 py-[17px] text-[clamp(0.9rem,2vw,1rem)] font-semibold text-white shadow-[0_4px_24px_rgba(115,66,226,0.28)]" onClick={openGenerator} type="button" whileHover={{ scale: 1.04, filter: "brightness(1.1)" }} whileTap={{ scale: 0.96 }}>
            生成学习资源 <ArrowRightCircle size={20} strokeWidth={1.8} />
          </motion.button>
        </motion.div>
        {schemeB ? (
          <motion.aside className="mt-10 hidden w-[270px] shrink-0 rounded-[1.75rem] bg-[#F2F2EE]/82 p-6 text-[#192837] shadow-[0_18px_60px_rgba(25,40,55,0.12)] backdrop-blur-[4px] lg:mt-0 lg:block" style={reducedMotion ? undefined : { x: mainX, y: mainY }} aria-label="XH Agent 工作流">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#192837]/55">协同工作流</p>
            <h2 className="mt-2 font-[var(--font-heading)] text-2xl leading-tight">每一步都有依据</h2>
            <ol className="mt-6 grid gap-4">
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
            <span className="shrink-0 rounded-full bg-[#192837]/[0.08] px-3 py-2 text-xs font-semibold">{panelDetails[activePanel].metric}</span>
          </div>
        </div>
      </motion.section>
      <MobileMenu onNavigate={selectPanel} onOpenGenerator={openGenerator} onOpenWorkspace={() => { setMenuOpen(false); setWorkspaceOpen(true); }} onOpenKb={() => { setMenuOpen(false); setKbOpen(true); }} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <KnowledgeManager open={kbOpen} onClose={() => setKbOpen(false)} />
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
                <fieldset className="grid gap-3"><legend className="text-lg font-semibold">输出设置</legend><span className="text-sm font-medium">资源类型，可多选</span><div className="flex flex-wrap gap-2">{resourceOptions.map((option) => <button aria-pressed={resourceTypes.includes(option.id)} className={`rounded-full px-3 py-2 text-sm font-medium transition ${resourceTypes.includes(option.id) ? "bg-[#7342E2] text-white" : "bg-[#192837]/[0.08] hover:bg-[#192837]/[0.14]"}`} key={option.id} onClick={() => toggleResourceType(option.id)} type="button">{option.label}</button>)}</div><label className="mt-2 flex cursor-pointer items-center gap-3 text-sm font-semibold"><input checked={demoMode} className="h-5 w-5 accent-[#7342E2]" onChange={(event) => setDemoMode(event.target.checked)} type="checkbox" />使用演示数据</label></fieldset>
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
            <motion.aside aria-label="学习工作台" className={`fixed bottom-0 right-0 top-0 z-40 flex flex-col overflow-y-auto bg-[#F2F2EE] p-6 text-[#192837] shadow-[-20px_0_70px_rgba(25,40,55,0.25)] transition-[width] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] sm:p-9 ${workspaceExpanded ? "w-full" : "w-[min(100%,600px)]"}`} initial={reducedMotion ? false : { x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} onScroll={(event) => setShowWorkspaceTopButton(event.currentTarget.scrollTop > 320)} ref={workspaceScrollRef} transition={{ duration: 0.42, ease }}>
              <div className={`flex items-start justify-between gap-5 ${workspaceExpanded ? "mx-auto w-full max-w-[1120px]" : ""}`}><div><p className="text-xs font-semibold tracking-[0.12em] text-[#192837]/55">学习工作台</p><h2 className="mt-2 font-[var(--font-heading)] text-3xl leading-tight">协同任务状态</h2></div><div className="flex items-center gap-2"><button aria-label={workspaceExpanded ? "收缩为侧边栏" : "全屏展开"} className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#192837]/[0.08] transition-transform hover:scale-105" onClick={() => setWorkspaceExpanded((expanded) => !expanded)} title={workspaceExpanded ? "收缩为侧边栏" : "全屏展开"} type="button">{workspaceExpanded ? <Minimize2 size={19} strokeWidth={1.8} /> : <Maximize2 size={19} strokeWidth={1.8} />}</button><button aria-label="关闭" className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#192837]/[0.08] transition-transform hover:scale-105" onClick={() => { setWorkspaceExpanded(false); setWorkspaceOpen(false); }} title="关闭工作台" type="button"><X size={20} strokeWidth={1.8} /></button></div></div>
               {workspaceExpanded ? <ExpandedWorkspaceLayout generationResult={generationResult} topic={topic} selectedResource={selectedResource} setSelectedResource={selectWorkspaceResource} activeStep={activeStep} setActiveStep={setActiveStep} selectedQualityGate={selectedQualityGate} setSelectedQualityGate={setSelectedQualityGate} onApplyRevision={applyRevision} onOpenWorkflow={(index) => setWorkspaceDialog({ kind: "workflow", index })} onOpenQualityGate={(id) => setWorkspaceDialog({ kind: "quality", id })} /> : null}
               {resourceReady && generationResult ? (
                 <section className={`mt-7 rounded-2xl bg-[#192837] p-5 text-white shadow-[0_20px_50px_rgba(25,40,55,0.18)] sm:p-7 ${workspaceExpanded ? "hidden" : ""}`}>
                  <div className="mx-auto max-w-[80ch]">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <p className="text-xs font-semibold text-white/60">本次生成结果</p>
                        <h3 className="mt-2 text-xl font-semibold leading-tight">{topic}</h3>
                      </div>
                      <span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/90">{generationResult.mode === "demo" ? "本地演示" : "DeepSeek Chat"}</span>
                    </div>
                    {generationResult.diagnosis?.summary ? <p className="mt-4 max-w-[76ch] text-[0.96rem] leading-7 text-white/85">诊断：{generationResult.diagnosis.summary}</p> : null}
                    <div className="mt-6 flex flex-wrap gap-2" aria-label="资源类型">
                      {(generationResult.resources ?? []).map((resource) => (
                        <button aria-pressed={selectedResource === resource.resource_type} className={`rounded-full px-4 py-2.5 text-sm font-semibold transition ${selectedResource === resource.resource_type ? "bg-white text-[#192837]" : "bg-white/15 text-white hover:bg-white/25"}`} key={resource.resource_type} onClick={() => setSelectedResource(resource.resource_type)} type="button">
                          {resourceLabel(resource.resource_type)}
                        </button>
                      ))}
                    </div>
                  </div>
                  {selectedResource ? (() => {
                    const resource = generationResult.resources?.find((item) => item.resource_type === selectedResource);
                    const resourceIndex = generationResult.resources?.findIndex((entry) => entry.resource_type === selectedResource);
                    const audit = generationResult.audit?.find((item) => item.resource_type === selectedResource || item.resource_index === resourceIndex);
                    return resource ? (
                      <motion.article className="mx-auto mt-6 max-w-[80ch] rounded-2xl bg-[#102333] p-5 shadow-inner shadow-black/10 sm:p-7" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} key={selectedResource}>
                        <header className="flex flex-wrap items-start justify-between gap-4">
                          <div className="max-w-2xl">
                            <p className="text-xs font-semibold text-white/60">资源预览</p>
                            <h4 className="mt-2 text-xl font-semibold leading-tight text-white">{resource.title}</h4>
                          </div>
                          {resource.estimated_duration_minutes ? <span className="rounded-full bg-white/10 px-3 py-2 text-xs font-semibold text-white/80">预计 {resource.estimated_duration_minutes} 分钟</span> : null}
                        </header>
                        {resource.key_takeaways?.length ? (
                          <aside className="mt-6 rounded-xl bg-white/[0.07] p-4">
                            <p className="text-xs font-semibold text-white/60">学习重点</p>
                            <ul className="mt-3 grid gap-2 pl-5 text-sm leading-6 text-white/85 marker:text-[#B99DFF]">
                              {resource.key_takeaways.map((takeaway, index) => <li key={`${takeaway}-${index}`}>{takeaway}</li>)}
                            </ul>
                          </aside>
                        ) : null}
                        <div className="mt-6"><ResourceMarkdown content={resource.content || ""} /></div>
                        <LearningTools onApplyRevision={applyRevision} resource={resource} topic={topic} />
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
                        {index === 0 ? <><p className="font-semibold text-[#192837]">学情诊断</p><p className="mt-2">{generationResult?.diagnosis?.summary || "暂无诊断结果。请先生成学习资源。"}</p><div className="mt-3 flex flex-wrap gap-2"><span className="rounded-full bg-white/70 px-3 py-1 text-xs">学习风格：{generationResult?.diagnosis?.learning_style || "未返回"}</span><span className="rounded-full bg-white/70 px-3 py-1 text-xs">建议难度：{generationResult?.diagnosis?.recommended_difficulty || "未返回"}</span></div>{generationResult?.diagnosis?.skill_gaps?.length ? <ul className="mt-3 grid gap-1 text-xs">{generationResult.diagnosis.skill_gaps.map((gap, gapIndex) => <li key={`${gap.topic}-${gapIndex}`}>知识缺口：{gap.topic || "未命名"} {gap.priority ? `(${gap.priority})` : ""}</li>)}</ul> : null}</> : null}
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
                      {workspaceDialog.kind === "workflow" && workspaceDialog.index === 0 ? <><p className="text-sm font-semibold text-white/60">学习画像诊断</p><p className="mt-3 text-sm leading-7 text-white/85">{generationResult?.diagnosis?.summary || "生成资源后将展示学习目标、基础能力和知识缺口诊断。"}</p>{generationResult?.diagnosis?.skill_gaps?.length ? <ul className="mt-5 grid gap-2 text-sm text-white/80">{generationResult.diagnosis.skill_gaps.map((gap, index) => <li className="rounded-xl bg-white/[0.08] px-4 py-3" key={`dialog-gap-${index}`}>{gap.topic || "待补充知识点"}{gap.priority ? <span className="ml-2 text-white/55">· 优先级 {gap.priority}</span> : null}</li>)}</ul> : null}</> : null}
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
