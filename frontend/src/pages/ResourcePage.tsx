/** 学习资源展示页 — 渲染Markdown讲义/指南/试题 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Card, Typography, Spin, Tag, Space, Empty, Button } from "antd";
import { FileTextOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getResource } from "../services/api";

export default function ResourcePage() {
  const { id } = useParams<{ id: string }>();
  const [resource, setResource] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    getResource(id)
      .then(setResource)
      .catch(() => setResource(null))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <Spin style={{ display: "block", margin: "100px auto" }} />;
  if (!resource) return <Empty description="资源不存在" />;

  const typeLabel: Record<string, string> = {
    lecture: "定制讲义",
    guide: "实操指南",
    quiz: "分阶测试题",
    case_study: "案例研习",
    micro_project: "微项目任务",
  };

  return (
    <div style={{ maxWidth: 900, margin: "20px auto" }}>
      <Card
        title={
          <Space>
            <FileTextOutlined />
            <Typography.Title level={4} style={{ margin: 0 }}>
              {resource.title}
            </Typography.Title>
          </Space>
        }
        extra={
          <Space>
            <Tag color="blue">{typeLabel[resource.resource_type] || resource.resource_type}</Tag>
            <Tag>{resource.difficulty_level}</Tag>
            <Tag>{resource.estimated_duration_minutes}分钟</Tag>
          </Space>
        }
      >
        {/* 引用溯源 */}
        {resource.citations?.length > 0 && (
          <Card title="知识溯源引用" size="small" style={{ marginBottom: 20 }}>
            {resource.citations.map((c: any, i: number) => (
              <Typography.Paragraph key={i} type="secondary" style={{ fontSize: "0.85em" }}>
                [{i + 1}] {c.cite_text}
                {c.usage && <Tag style={{ marginLeft: 8 }}>{c.usage}</Tag>}
              </Typography.Paragraph>
            ))}
          </Card>
        )}

        {/* Markdown内容 */}
        <div className="markdown-body">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {resource.content || "暂无内容"}
          </ReactMarkdown>
        </div>

        {/* 如果类型是测验，显示答题入口 */}
        {resource.resource_type === "quiz" && (
          <div style={{ marginTop: 24, textAlign: "center" }}>
            <Button type="primary" size="large" href={`/quiz/${id}`}>
              开始答题 →
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
