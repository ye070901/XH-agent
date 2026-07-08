/** 答题互动页 — 提交答案 + 获取反馈Agent决策 */
import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Card, Typography, Button, Radio, Space, Alert, Result, Tag } from "antd";
import { CheckCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import { submitQuiz } from "../services/api";

// 模拟试题（实际应从API获取）
const MOCK_QUESTIONS = [
  {
    id: "q1",
    type: "choice",
    question: "在PLC控制系统中，紧急停止按钮应该连接到哪里？",
    options: ["A. PLC输入端", "B. 安全继电器回路", "C. PLC输出端", "D. 触摸屏"],
    answer: "B",
    topic: "PLC安全",
  },
  {
    id: "q2",
    type: "choice",
    question: "工业机器人TCP（工具中心点）的标定目的是什么？",
    options: [
      "A. 提高机器人速度",
      "B. 确定工具相对于法兰的精确位置",
      "C. 延长机器人寿命",
      "D. 减少电机发热",
    ],
    answer: "B",
    topic: "工业机器人",
  },
  {
    id: "q3",
    type: "choice",
    question: "MES系统的核心功能不包括以下哪项？",
    options: ["A. 生产调度", "B. 质量管理", "C. 财务报表", "D. 数据追溯"],
    answer: "C",
    topic: "MES系统",
  },
];

export default function QuizPage() {
  const { resourceId } = useParams<{ resourceId: string }>();
  const navigate = useNavigate();

  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const handleSelect = (qId: string, value: string) => {
    if (submitted) return;
    setAnswers((prev) => ({ ...prev, [qId]: value }));
  };

  const handleSubmit = async () => {
    const correctCount = MOCK_QUESTIONS.filter((q) => answers[q.id] === q.answer).length;
    const correctRate = correctCount / MOCK_QUESTIONS.length;
    const topicBreakdown: Record<string, number> = {};
    MOCK_QUESTIONS.forEach((q) => {
      if (!topicBreakdown[q.topic]) topicBreakdown[q.topic] = 0;
      if (answers[q.id] === q.answer) topicBreakdown[q.topic] += 1;
    });
    Object.keys(topicBreakdown).forEach((k) => {
      const count = MOCK_QUESTIONS.filter((q) => q.topic === k).length;
      topicBreakdown[k] = count > 0 ? topicBreakdown[k] / count : 0;
    });

    setLoading(true);
    try {
      const feedback = await submitQuiz({
        learner_id: sessionStorage.getItem("learner_id") || "unknown",
        resource_id: resourceId,
        correct_rate: correctRate,
        topic_breakdown: topicBreakdown,
        answers: Object.entries(answers).map(([qId, ans]) => ({
          question_id: qId,
          user_answer: ans,
        })),
      });
      setResult({ ...feedback, correctCount, total: MOCK_QUESTIONS.length, correctRate });
      setSubmitted(true);
    } catch {
      setResult({ correctCount, total: MOCK_QUESTIONS.length, correctRate, action: "continue", reason: "本地评测完成" });
      setSubmitted(true);
    } finally {
      setLoading(false);
    }
  };

  if (submitted && result) {
    const actionLabels: Record<string, string> = {
      simplify: "降维解释",
      advance: "进阶挑战",
      regenerate: "重新生成",
      continue: "继续当前路径",
    };

    return (
      <div style={{ maxWidth: 600, margin: "40px auto" }}>
        <Result
          status={result.correctRate > 0.7 ? "success" : "warning"}
          title={`答题完成！正确率 ${Math.round(result.correctRate * 100)}%`}
          subTitle={`${result.correctCount} / ${result.total} 题正确`}
        >
          <Alert
            type={result.action === "simplify" ? "warning" : result.action === "advance" ? "success" : "info"}
            message={`反馈Agent决策：${actionLabels[result.action] || result.action}`}
            description={result.reason}
            showIcon
            style={{ marginBottom: 16 }}
          />
          <Space>
            <Button type="primary" onClick={() => { setSubmitted(false); setAnswers({}); setResult(null); }}>
              重新作答
            </Button>
            <Button onClick={() => navigate("/report")}>查看学情报告</Button>
          </Space>
        </Result>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 800, margin: "20px auto" }}>
      <Typography.Title level={3}>分阶测试</Typography.Title>
      <Typography.Paragraph type="secondary">
        完成以下测试题，反馈Agent将根据正确率决策下一步学习方向
      </Typography.Paragraph>

      {MOCK_QUESTIONS.map((q, idx) => (
        <Card key={q.id} title={`第 ${idx + 1} 题`} style={{ marginBottom: 16 }}
          extra={<Tag>{q.topic}</Tag>}>
          <Typography.Paragraph strong>{q.question}</Typography.Paragraph>
          <Radio.Group
            value={answers[q.id]}
            onChange={(e) => handleSelect(q.id, e.target.value)}
          >
            <Space direction="vertical">
              {q.options.map((opt) => (
                <Radio key={opt} value={opt[0]}>
                  {opt}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </Card>
      ))}

      <Button
        type="primary"
        size="large"
        block
        onClick={handleSubmit}
        loading={loading}
        disabled={Object.keys(answers).length < MOCK_QUESTIONS.length}
      >
        提交答案 → 获取Agent反馈
      </Button>
    </div>
  );
}
