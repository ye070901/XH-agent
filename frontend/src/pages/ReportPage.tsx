/** 学情报告页 — 知识雷达图 + 盲区分析 + 学习路径 */
import { useEffect, useState } from "react";
import { Card, Typography, Spin, Empty, Table, Tag, Progress } from "antd";
import { getReport } from "../services/api";

export default function ReportPage() {
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const learnerId = sessionStorage.getItem("learner_id") || "";

  useEffect(() => {
    if (!learnerId) {
      setLoading(false);
      return;
    }
    getReport(learnerId)
      .then(setReport)
      .catch(() => setReport(null))
      .finally(() => setLoading(false));
  }, [learnerId]);

  if (loading) return <Spin style={{ display: "block", margin: "100px auto" }} />;
  if (!report) return <Empty description="暂无报告数据，请先生成学习资源" />;

  const gaps = report.skill_gap_analysis || [];
  const radar = report.knowledge_radar || {};

  const gapColumns = [
    { title: "知识点", dataIndex: "topic", key: "topic" },
    {
      title: "当前水平",
      dataIndex: "current_level",
      key: "current",
      render: (v: number) => <Progress percent={Math.round(v * 100)} size="small" />,
    },
    {
      title: "目标水平",
      dataIndex: "target_level",
      key: "target",
      render: (v: number) => <Progress percent={Math.round(v * 100)} size="small" strokeColor="#52c41a" />,
    },
    {
      title: "优先级",
      dataIndex: "priority",
      key: "priority",
      render: (v: string) => {
        const colors: Record<string, string> = { critical: "red", high: "orange", medium: "blue", low: "green" };
        return <Tag color={colors[v] || "default"}>{v}</Tag>;
      },
    },
    { title: "原因", dataIndex: "reason", key: "reason" },
  ];

  return (
    <div style={{ maxWidth: 1000, margin: "20px auto" }}>
      <Typography.Title level={3}>学情综合报告</Typography.Title>

      {/* 知识掌握度 */}
      <Card title="知识掌握度" style={{ marginBottom: 20 }}>
        {Object.keys(radar).length === 0 ? (
          <Empty description="暂无数据" />
        ) : (
          Object.entries(radar).map(([topic, level]) => (
            <div key={topic} style={{ marginBottom: 12 }}>
              <Typography.Text>{topic}</Typography.Text>
              <Progress percent={Math.round((level as number) * 100)} />
            </div>
          ))
        )}
      </Card>

      {/* 技能盲区 */}
      <Card title="技能盲区分析" style={{ marginBottom: 20 }}>
        <Table
          dataSource={gaps}
          columns={gapColumns}
          rowKey="topic"
          pagination={false}
          size="small"
        />
      </Card>

      {/* 学习路径 */}
      {report.learning_path && (
        <Card title="学习路径规划" style={{ marginBottom: 20 }}>
          <Typography.Paragraph>
            预计总时长：{report.learning_path.total_estimated_hours}小时
          </Typography.Paragraph>
          {report.learning_path.nodes?.map((node: any) => (
            <Card key={node.node_id} size="small" style={{ marginBottom: 8 }}>
              <Typography.Text strong>{node.title}</Typography.Text>
              <br />
              <Typography.Text type="secondary">
                难度: {node.difficulty} | 时长: {node.estimated_duration_minutes}分钟
                {node.is_completed && <Tag color="success" style={{ marginLeft: 8 }}>已完成</Tag>}
              </Typography.Text>
            </Card>
          ))}
        </Card>
      )}
    </div>
  );
}
