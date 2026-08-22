export type ClarificationQuestion = {
  id: "scope" | "outcome" | "timeline";
  label: string;
  helper: string;
  options?: string[];
};

export type GoalAssessment =
  | { status: "ready"; normalizedGoal: string }
  | { status: "needs_clarification"; reason: string; questions: ClarificationQuestion[] };

export type QuizQuestion = {
  id: string;
  stem: string;
  options: Array<{ id: string; text: string }>;
  answer: string;
  explanation: string;
  knowledgeId?: string;
};

export type Quiz = {
  title: string;
  questions: QuizQuestion[];
};

export type LearnerQuestionResponse = {
  answer: string;
  suggestions: string[];
  revisionTitle: string;
  revisionContent: string;
};

export type QuizSubmissionResult = {
  correct_count: number;
  total: number;
  score: number;
  details: Array<{
    question_id: string;
    knowledge_id: string;
    submitted_answer: string;
    correct: boolean;
    standard_answer: string;
    explanation: string;
  }>;
  learning_advice: string[];
  profile_snapshot_id: string;
};

function getLearnerId() {
  const storageKey = "xh-agent-learner-id";
  const existing = window.localStorage.getItem(storageKey);
  if (existing) return existing;
  const suffix = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}_${Math.random().toString(36).slice(2)}`;
  const learnerId = `learner_${suffix}`;
  window.localStorage.setItem(storageKey, learnerId);
  return learnerId;
}

export async function submitQuiz(
  quiz: Quiz,
  answers: Record<string, string>,
  topic: string,
  resourceId?: string,
): Promise<QuizSubmissionResult> {
  const apiBase = window.localStorage.getItem("xh-agent-api-base") || "http://localhost:8000";
  const response = await fetch(apiBase + "/api/exams/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      learner_id: getLearnerId(),
      topic: topic || "general",
      resource_id: resourceId,
      questions: quiz.questions.map((question) => ({
        id: question.id,
        question_type: "choice",
        standard_answer: question.answer,
        explanation: question.explanation,
        knowledge_id: question.knowledgeId || topic || "general",
      })),
      answers: quiz.questions.map((question) => ({
        question_id: question.id,
        answer: answers[question.id] || "",
      })),
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `API ${response.status}`);
  }
  return payload as QuizSubmissionResult;
}

const broadGoalPatterns = [
  /^学习.+$/,
  /^了解.+$/,
  /^掌握.+$/,
  /^入门.+$/,
  /^机器人$/,
  /^人工智能$/,
  /^编程$/,
];

export async function assessLearningGoal(goal: string): Promise<GoalAssessment> {
  // Frontend mock adapter. Replace this function with POST /api/goals/assess later.
  await wait(280);
  const normalizedGoal = goal.replace(/\s+/g, " ").trim();
  const isBroad = normalizedGoal.length < 14 || broadGoalPatterns.some((pattern) => pattern.test(normalizedGoal));

  if (!isBroad) return { status: "ready", normalizedGoal };

  return {
    status: "needs_clarification",
    reason: "当前目标还缺少学习范围、预期成果或时间边界。补充这些信息后，资源会更贴近你的实际任务。",
    questions: [
      {
        id: "scope",
        label: "优先聚焦哪一部分？",
        helper: "选择一个最想先解决的范围。",
        options: ["基础原理", "设备操作", "编程与调试", "故障诊断"],
      },
      {
        id: "outcome",
        label: "完成后希望能做到什么？",
        helper: "例如：独立完成一次示教、能排查常见报警。",
      },
      {
        id: "timeline",
        label: "计划在多长时间内完成？",
        helper: "这会影响资源深度和练习安排。",
        options: ["3 天内", "1 周内", "2-4 周", "长期学习"],
      },
    ],
  };
}

export function refineLearningGoal(goal: string, answers: Record<string, string>) {
  const details = [
    answers.scope ? "重点学习" + answers.scope : "",
    answers.outcome ? "目标是" + answers.outcome : "",
    answers.timeline ? "计划在" + answers.timeline + "完成" : "",
  ].filter(Boolean);
  return details.length ? goal.trim() + "；" + details.join("；") + "。" : goal.trim();
}

export function createDemoQuiz(topic: string): Quiz {
  return {
    title: (topic || "学习主题") + "基础测试",
    questions: [
      {
        id: "q1",
        stem: "开始一个新的实践任务前，最合适的第一步是什么？",
        options: [
          { id: "A", text: "直接执行完整流程" },
          { id: "B", text: "确认目标、边界和安全条件" },
          { id: "C", text: "跳过基础概念学习" },
          { id: "D", text: "只记录最终结果" },
        ],
        answer: "B",
        explanation: "先确认任务目标、边界和安全条件，才能决定后续学习与操作的正确顺序。",
      },
      {
        id: "q2",
        stem: "遇到无法理解的步骤时，更有效的学习策略是？",
        options: [
          { id: "A", text: "忽略疑问，继续往下看" },
          { id: "B", text: "只背诵结论" },
          { id: "C", text: "记录疑问，并结合当前资源提出具体问题" },
          { id: "D", text: "重新开始，不保留已有进度" },
        ],
        answer: "C",
        explanation: "把疑问与当前资源的具体段落或操作关联，系统才能给出更准确的补充与练习建议。",
      },
    ],
  };
}

export async function askStudyQuestion(question: string, topic: string, resourceContext = ""): Promise<LearnerQuestionResponse> {
  const apiBase = window.localStorage.getItem("xh-agent-api-base") || "http://localhost:8000";
  const response = await fetch(apiBase + "/api/learning-questions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      topic,
      resource_context: resourceContext,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `API ${response.status}`);
  }
  if (typeof payload.answer !== "string" || !payload.answer.trim()) {
    throw new Error("The learning-answer service returned no answer.");
  }
  return {
    answer: payload.answer,
    suggestions: Array.isArray(payload.suggestions) ? payload.suggestions.map(String) : [],
    revisionTitle: typeof payload.revisionTitle === "string" ? payload.revisionTitle : "针对疑问的补充说明",
    revisionContent: typeof payload.revisionContent === "string" ? payload.revisionContent : payload.answer,
  };

  // Frontend mock adapter. Replace this function with POST /api/sessions/{session_id}/questions later.
  await wait(420);
  const subject = topic || "当前学习主题";
  return {
    answer: "关于“" + question + "”，建议先回到 " + subject + " 的核心概念，确认它解决的任务、输入条件和操作顺序。不要只记结论，最好用一个小练习验证自己的理解。",
    suggestions: ["先复习资源中的关键概念与前置条件", "完成一个最小练习并记录结果", "将仍未理解的步骤继续拆成具体问题"],
    revisionTitle: "针对疑问的补充说明",
    revisionContent: "围绕“" + question + "”补充：先明确它在 " + subject + " 中的作用，再把步骤拆为“条件 -> 操作 -> 结果”。完成后用一个小型实践验证判断是否正确。",
  };
}

function wait(milliseconds: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));
}
