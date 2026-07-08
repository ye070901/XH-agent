/** 资源生成页 — 核心：触发Agent协同 + 实时可视化 */
import { useState, useEffect, useRef } from "react";
import {
  Button, Card, Typography, Steps, Tag, Space, Spin, Alert, Empty, List, Progress,
} from "antd";
import {
  ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined,
  LoadingOutlined, ExclamationCircleOutlined,
} from "@ant-design/icons";
import { startGeneration, getTaskStatus, connectAgentWS } from "../services/api";

const AGENT_NAMES: Record<string, string> = {
  diagnosis: "学情诊断Agent",
  retriever: "知识检索",
  generator: "知识生成Agent",
  reviewer: "审核裁判Agent",
  debate: "辩论引擎",
  planner: "路径规划Agent",
  system: "系统",
};

export default function GeneratePage() {
  const [taskId, setTaskId] = useState<string>("");
  const [status, setStatus] = useState<string>("idle"); // idle → running → completed
  const [progress, setProgress] = useState(0);
  const [currentAgent, setCurrentAgent] = useState("");
  const [logs, setLogs] = useState<any[]>([]);
  const [resources, setResources] = useState<any[]>([]);
  const [debates, setDebates] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const pollRef = useRef<any>(null);
  const wsCleanupRef = useRef<(() => void) | null>(null);

  // 读取之前创建的学习者数据
  const learnerData = (() => {
    try {
      const raw = sessionStorage.getItem("learner_data");
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  })();

  const startGenerate = async () => {
    if (!learnerData) return;
    setLoading(true);
    setResources([]);
    setDebates([]);
    setLogs([]);
    setError("");

    try {
      const res = await startGeneration({
        learner_data: learnerData,
        resource_types: ["lecture", "guide", "quiz"],
      });
      setTaskId(res.task_id);
      setStatus("running");
      setCurrentAgent("system");

      // 连接WebSocket实时接收Agent状态
      const cleanup = connectAgentWS(res.task_id, (msg) => {
        setLogs((prev) => [...prev, { ...msg, _time: Date.now() }]);
        if (msg.agent_name) setCurrentAgent(msg.agent_name);
        if (msg.data?.progress) setProgress(msg.data.progress);
      });
      wsCleanupRef.current = cleanup;

      // 同时轮询任务状态
      pollRef.current = setInterval(async () => {
        try {
          const data = await getTaskStatus(res.task_id);
          setProgress(data.progress_percent || 0);
          setCurrentAgent(data.current_agent || "");
          if (data.generated_resources?.length) {
            setResources(data.generated_resources);
          }
          if (data.debate_records?.length) {
            setDebates(data.debate_records);
          }
          if (data.status === "completed" || data.status === "failed") {
            setStatus(data.status);
            setError(data.error_message || "");
            clearInterval(pollRef.current);
          }
        } catch {}
      }, 2000);
    } catch (e: any) {
      setError(e.message || "生成失败");
      setStatus("failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (wsCleanupRef.current) wsCleanupRef.current();
    };
  }, []);

  const agentSteps = [
    { key: "diagnosis", title: "学情诊断" },
    { key: "generator", title: "资源生成" },
    { key: "reviewer", title: "内容审核" },
    { key: "debate", title: "辩论验证" },
    { key: "planner", title: "路径规划" },
  ];

  const currentStep = agentSteps.findIndex((s) => s.key === currentAgent);

  return (
    <div style={{ maxWidth: 1000, margin: "20px auto" }}>
      <Typography.Title level={3}>
        <ThunderboltOutlined /> 多Agent协同资源生成
      </Typography.Title>

      {!learnerData ? (
        <Alert
          type="warning"
          message="请先创建学习者画像"
          description="需要学习者画像数据才能触发Agent协同生成"
          showIcon
          action={<Button href="/profile">去创建</Button>}
        />
      ) : (
        <>
          {/* 触发按钮 */}
          <Card style={{ marginBottom: 20 }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Typography.Text>
                学习者：<Tag color="blue">{learnerData.name}</Tag>
                学历：<Tag>{learnerData.education_level}</Tag>
                专业：<Tag>{learnerData.major}</Tag>
              </Typography.Text>
              <Space>
                <Button
                  type="primary"
                  icon={<ThunderboltOutlined />}
                  onClick={startGenerate}
                  loading={loading}
                  disabled={status === "running"}
                  size="large"
                >
                  {status === "running" ? "生成中..." : "启动多Agent协同生成"}
                </Button>
                {taskId && <Tag>Task: {taskId}</Tag>}
              </Space>
            </Space>
          </Card>

          {/* 进度 */}
          {status === "running" && (
            <Card title="Agent协同进度" style={{ marginBottom: 20 }}>
              <Progress percent={Math.round(progress)} status="active" />
              <Steps
                current={Math.max(0, currentStep)}
                items={agentSteps}
                style={{ marginTop: 20 }}
              />
              <Typography.Text style={{ marginTop: 12, display: "block" }}>
                当前Agent：<Tag color="processing">{AGENT_NAMES[currentAgent] || currentAgent}</Tag>
                <Spin indicator={<LoadingOutlined />} size="small" style={{ marginLeft: 8 }} />
              </Typography.Text>
            </Card>
          )}

          {/* 错误 */}
          {error && (
            <Alert type="error" message="生成失败" description={error} showIcon style={{ marginBottom: 20 }} />
          )}

          {/* Agent活动日志 */}
          {logs.length > 0 && (
            <Card title="Agent活动日志" size="small" style={{ marginBottom: 20 }}>
              <List
                size="small"
                dataSource={logs.slice(-20)}
                renderItem={(log: any) => (
                  <List.Item>
                    <Space>
                      <Tag color={log.agent_state === "error" ? "red" : "green"}>
                        {AGENT_NAMES[log.agent_name] || log.agent_name}
                      </Tag>
                      <Typography.Text type="secondary" style={{ fontSize: "0.85em" }}>
                        {log.message}
                      </Typography.Text>
                    </Space>
                  </List.Item>
                )}
              />
            </Card>
          )}

          {/* 辩论记录 */}
          {debates.length > 0 && (
            <Card
              title={
                <Space>
                  <ExclamationCircleOutlined style={{ color: "#faad14" }} />
                  辩论记录（{debates.length}次）
                </Space>
              }
              size="small"
              style={{ marginBottom: 20 }}
            >
              {debates.map((d: any, i: number) => (
                <Alert
                  key={i}
                  type={d.final_verdict === "approved" ? "success" : "warning"}
                  message={`辩论 #${i + 1}: ${d.final_verdict}`}
                  description={d.resolution}
                  showIcon
                  icon={
                    d.final_verdict === "approved"
                      ? <CheckCircleOutlined />
                      : <CloseCircleOutlined />
                  }
                  style={{ marginBottom: 8 }}
                />
              ))}
            </Card>
          )}

          {/* 生成结果 */}
          {resources.length > 0 && (
            <Card
              title={`生成资源（${resources.length}个）`}
              extra={
                status === "completed" && (
                  <Tag color="success" icon={<CheckCircleOutlined />}>全部完成</Tag>
                )
              }
            >
              <List
                dataSource={resources}
                renderItem={(res: any) => (
                  <List.Item
                    extra={
                      <Button
                        type="link"
                        href={`/resource/${res.resource_id}`}
                        target="_blank"
                      >
                        查看详情 →
                      </Button>
                    }
                  >
                    <List.Item.Meta
                      title={
                        <Space>
                          <Tag>{res.resource_type === "lecture" ? "讲义" : res.resource_type === "guide" ? "实操指南" : "测试题"}</Tag>
                          {res.title}
                        </Space>
                      }
                      description={`难度: ${res.difficulty_level} | 预计时长: ${res.estimated_duration_minutes}分钟`}
                    />
                  </List.Item>
                )}
              />
            </Card>
          )}

          {/* 空状态 */}
          {status === "idle" && (
            <Empty description='点击"启动多Agent协同生成"开始' />
          )}
        </>
      )}
    </div>
  );
}
