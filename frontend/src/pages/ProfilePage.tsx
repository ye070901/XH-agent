/** 学习者画像录入页 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Form, Input, Select, InputNumber, Button, Card, Typography, Space, message } from "antd";
import { createLearner } from "../services/api";

export default function ProfilePage() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const onFinish = async (values: any) => {
    setLoading(true);
    try {
      const result = await createLearner({
        name: values.name,
        education: {
          level: values.education_level,
          major: values.major,
          school: values.school,
        },
        experience: {
          years: values.work_years || 0,
          industry: values.industry,
          positions: values.positions ? values.positions.split(",") : [],
          skills_used: values.skills_used ? values.skills_used.split(",") : [],
        },
        pretest_results: [],
      });
      message.success("画像创建成功");
      // 存到 session，生成页面用
      sessionStorage.setItem("learner_id", result.learner_id);
      sessionStorage.setItem("learner_data", JSON.stringify(values));
      navigate("/generate");
    } catch (e: any) {
      message.error("创建失败: " + (e.message || "未知错误"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 700, margin: "20px auto" }}>
      <Typography.Title level={3}>创建学习者画像</Typography.Title>
      <Card>
        <Form layout="vertical" onFinish={onFinish}>
          <Form.Item label="姓名" name="name" rules={[{ required: true }]}>
            <Input placeholder="请输入姓名" />
          </Form.Item>

          <Form.Item label="学历" name="education_level" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "high_school", label: "高中" },
                { value: "junior_college", label: "专科" },
                { value: "bachelor", label: "本科" },
                { value: "master", label: "硕士" },
                { value: "phd", label: "博士" },
              ]}
            />
          </Form.Item>

          <Form.Item label="专业" name="major" rules={[{ required: true }]}>
            <Input placeholder="如：机械工程" />
          </Form.Item>

          <Form.Item label="学校" name="school">
            <Input placeholder="毕业院校" />
          </Form.Item>

          <Space size="large">
            <Form.Item label="工作年限" name="work_years">
              <InputNumber min={0} max={50} placeholder="0" />
            </Form.Item>

            <Form.Item label="行业" name="industry">
              <Input placeholder="如：智能制造" />
            </Form.Item>
          </Space>

          <Form.Item label="曾任岗位" name="positions">
            <Input placeholder="多个岗位用逗号分隔" />
          </Form.Item>

          <Form.Item label="掌握的技能" name="skills_used">
            <Input placeholder="多个技能用逗号分隔" />
          </Form.Item>

          <Form.Item label="学习目标" name="learning_goal">
            <Input.TextArea rows={3} placeholder="你想通过本次学习达到什么目标？" />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              提交画像 → 开始生成
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
