/** 整体布局 — 顶部导航 + 内容区 */
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { Layout, Menu } from "antd";
import {
  HomeOutlined, UserOutlined, ThunderboltOutlined,
  FileTextOutlined, BarChartOutlined,
} from "@ant-design/icons";

const { Header, Content } = Layout;

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  const items = [
    { key: "/", icon: <HomeOutlined />, label: "首页" },
    { key: "/profile", icon: <UserOutlined />, label: "学习者画像" },
    { key: "/generate", icon: <ThunderboltOutlined />, label: "资源生成" },
    { key: "/report", icon: <BarChartOutlined />, label: "学情报告" },
  ];

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header style={{ display: "flex", alignItems: "center", padding: "0 24px" }}>
        <span style={{ color: "#fff", fontSize: "1em", fontWeight: 600, marginRight: 32, whiteSpace: "nowrap" }}>
          🧠 多Agent协同决策系统
        </span>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={items}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1, minWidth: 0 }}
        />
      </Header>
      <Content style={{ padding: "24px", background: "#f5f5f5" }}>
        <Outlet />
      </Content>
    </Layout>
  );
}
