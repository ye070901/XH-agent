import { Routes, Route } from "react-router-dom";
import { Layout } from "antd";
import AppLayout from "./components/AppLayout";
import HomePage from "./pages/HomePage";
import ProfilePage from "./pages/ProfilePage";
import GeneratePage from "./pages/GeneratePage";
import ResourcePage from "./pages/ResourcePage";
import ReportPage from "./pages/ReportPage";
import QuizPage from "./pages/QuizPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/generate" element={<GeneratePage />} />
        <Route path="/resource/:id" element={<ResourcePage />} />
        <Route path="/report" element={<ReportPage />} />
        <Route path="/quiz/:resourceId" element={<QuizPage />} />
      </Route>
    </Routes>
  );
}
