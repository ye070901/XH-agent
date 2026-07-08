/** API Service — axios封装 */
import axios from "axios";

const api = axios.create({
  baseURL: "/api/v1",
  timeout: 30000,
});

// ── 学习者 ──
export async function createLearner(data: any) {
  const res = await api.post("/learners", data);
  return res.data;
}

export async function getLearner(id: string) {
  const res = await api.get(`/learners/${id}`);
  return res.data;
}

// ── 资源生成 ──
export async function startGeneration(data: any) {
  const res = await api.post("/generate", data);
  return res.data;
}

export async function getTaskStatus(taskId: string) {
  const res = await api.get(`/generate/${taskId}`);
  return res.data;
}

// ── 资源 ──
export async function getResource(id: string) {
  const res = await api.get(`/resources/${id}`);
  return res.data;
}

// ── 答题 ──
export async function submitQuiz(data: any) {
  const res = await api.post("/quiz/submit", data);
  return res.data;
}

// ── 报告 ──
export async function getReport(learnerId: string) {
  const res = await api.get(`/report/${learnerId}`);
  return res.data;
}

// ── 知识库 ──
export async function uploadDocument(data: any) {
  const res = await api.post("/knowledge/upload", data);
  return res.data;
}

export async function getKnowledgeStatus() {
  const res = await api.get("/knowledge/status");
  return res.data;
}

// ── WebSocket ──
export function connectAgentWS(taskId: string, onMessage: (msg: any) => void) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  const ws = new WebSocket(`${protocol}//${host}/api/v1/ws/agent/${taskId}`);

  ws.onopen = () => console.log(`[WS] 已连接: ${taskId}`);
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch {}
  };
  ws.onclose = () => console.log(`[WS] 已断开: ${taskId}`);
  ws.onerror = (e) => console.error(`[WS] 错误: ${taskId}`, e);

  // 心跳
  const heartbeat = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send("ping");
  }, 15000);

  return () => {
    clearInterval(heartbeat);
    ws.close();
  };
}
