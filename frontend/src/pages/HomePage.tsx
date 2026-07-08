/** 首页 — 系统入口 */
import { useNavigate } from "react-router-dom";
import { Button, Card, Typography, Space } from "antd";
import { UserOutlined, ThunderboltOutlined, BarChartOutlined } from "@ant-design/icons";

export default function HomePage() {
  const navigate = useNavigate();

  return (
    <div style={{ maxWidth: 800, margin: "60px auto", textAlign: "center" }}>
      <Typography.Title level={1} style={{ fontSize: "2em" }}>
        领域知识个性化生成
        <br />
        与多智能体协同决策系统
      </Typography.Title>
      <Typography.Paragraph
        type="secondary"
        style={{ fontSize: "1.1em", marginBottom: 48 }}
      >
        5个Agent协同 · 辩论消除幻觉 · 知识溯源保障 · 动态迭代适配
      </Typography.Paragraph>

      <Space size="large">
        <Card
          hoverable
          style={{ width: 220 }}
          onClick={() => navigate("/profile")}
        >
          <UserOutlined style={{ fontSize: 36, color: "#4361ee", marginBottom: 12 }} />
          <Typography.Title level={4}>创建学习者画像</Typography.Title>
          <Typography.Paragraph type="secondary">
            输入学历、经历、测试成绩
          </Typography.Paragraph>
        </Card>

        <Card
          hoverable
          style={{ width: 220 }}
          onClick={() => navigate("/generate")}
        >
          <ThunderboltOutlined style={{ fontSize: 36, color: "#4361ee", marginBottom: 12 }} />
          <Typography.Title level={4}>生成学习资源</Typography.Title>
          <Typography.Paragraph type="secondary">
            多Agent协同生成定制资源
          </Typography.Paragraph>
        </Card>

        <Card
          hoverable
          style={{ width: 220 }}
          onClick={() => navigate("/report")}
        >
          <BarChartOutlined style={{ fontSize: 36, color: "#4361ee", marginBottom: 12 }} />
          <Typography.Title level={4}>查看学情报告</Typography.Title>
          <Typography.Paragraph type="secondary">
            知识图谱 · 学习路径 · 匹配置信度
          </Typography.Paragraph>
        </Card>
      </Space>
    </div>
  );
}
