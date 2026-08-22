export type WorkflowEvent = {
  task_id?: string;
  agent: string;
  status: "pending" | "running" | "done" | "error";
  message?: string;
  count?: number;
  timestamp?: string;
};

export const workflowStages = [
  { agent: "diagnosis", label: "学情诊断" },
  { agent: "retrieval", label: "知识检索" },
  { agent: "generation", label: "资源生成" },
  { agent: "audit", label: "内容审核" },
  { agent: "correction", label: "保真修正" },
] as const;

export function initialWorkflowEvents(): WorkflowEvent[] {
  return workflowStages.map((stage) => ({ agent: stage.agent, status: "pending" }));
}

export function mergeWorkflowEvent(events: WorkflowEvent[], incoming: WorkflowEvent): WorkflowEvent[] {
  const hasStage = events.some((event) => event.agent === incoming.agent);
  if (!hasStage) return [...events, incoming];
  return events.map((event) => event.agent === incoming.agent ? { ...event, ...incoming } : event);
}

export function websocketUrl(taskId: string) {
  const apiBase = window.localStorage.getItem("xh-agent-api-base") || "http://localhost:8000";
  const url = new URL(apiBase);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/task/" + encodeURIComponent(taskId);
  url.search = "";
  return url.toString();
}

export function subscribeWorkflow(taskId: string, onEvent: (event: WorkflowEvent) => void, onClosed: () => void) {
  const socket = new WebSocket(websocketUrl(taskId));
  socket.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as WorkflowEvent);
    } catch {
      // Ignore malformed server events so the learning flow remains usable.
    }
  };
  socket.onerror = () => onClosed();
  socket.onclose = () => onClosed();
  return () => socket.close();
}

export function simulateWorkflow(onEvent: (event: WorkflowEvent) => void) {
  const timers = workflowStages.map((stage, index) => window.setTimeout(() => {
    onEvent({ agent: stage.agent, status: "running", message: "正在处理" });
    window.setTimeout(() => onEvent({ agent: stage.agent, status: "done", message: "已完成" }), 420);
  }, index * 620));
  return () => timers.forEach((timer) => window.clearTimeout(timer));
}
