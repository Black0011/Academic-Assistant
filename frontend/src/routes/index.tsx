import { createBrowserRouter, Navigate } from "react-router-dom";

import { AuthProvider } from "@/components/auth/AuthProvider";
import { RequireAuth } from "@/components/auth/RequireAuth";
import { AppLayout } from "@/components/layout/AppLayout";
import { DashboardPage } from "@/pages/DashboardPage";
import { KnowledgeLibraryPage } from "@/pages/KnowledgeLibraryPage";
import { LoginPage } from "@/pages/LoginPage";
import { ManuscriptsPage } from "@/pages/ManuscriptsPage";
import { McpServersPage } from "@/pages/McpServersPage";
import { MemoryPage } from "@/pages/MemoryPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { PaperChatPage } from "@/pages/PaperChatPage";
import { PaperWriterPage } from "@/pages/PaperWriterPage";
import { PlannerPage } from "@/pages/PlannerPage";
import { ProposalsPage } from "@/pages/ProposalsPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { ResearchConsolePage } from "@/pages/ResearchConsolePage";
import { RevisionPage } from "@/pages/RevisionPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SkillsPage } from "@/pages/SkillsPage";
import { TaskDetailPage } from "@/pages/TaskDetailPage";
import { TasksPage } from "@/pages/TasksPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: (
      <AuthProvider>
        <RequireAuth />
      </AuthProvider>
    ),
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: "research", element: <ResearchConsolePage /> },
          { path: "papers", element: <ManuscriptsPage /> },
          { path: "papers/:manuscriptId", element: <PaperWriterPage /> },
          // P12.3 — primary writing entrypoint; both /workbench and the
          // legacy /chat point at the same component so bookmarks survive
          // the rename. Internal links use /workbench/*.
          { path: "workbench", element: <PaperChatPage /> },
          { path: "workbench/:manuscriptId", element: <PaperChatPage /> },
          { path: "chat", element: <PaperChatPage /> },
          { path: "chat/:manuscriptId", element: <PaperChatPage /> },
          { path: "revision", element: <RevisionPage /> },
          { path: "library", element: <KnowledgeLibraryPage /> },
          { path: "library/:docId", element: <KnowledgeLibraryPage /> },
          { path: "memory", element: <MemoryPage /> },
          { path: "skills", element: <SkillsPage /> },
          { path: "skills/:name", element: <SkillsPage /> },
          { path: "mcp", element: <McpServersPage /> },
          { path: "planner", element: <PlannerPage /> },
          { path: "proposals", element: <ProposalsPage /> },
          { path: "proposals/:proposalId", element: <ProposalsPage /> },
          { path: "tasks", element: <TasksPage /> },
          { path: "tasks/:taskId", element: <TaskDetailPage /> },
          { path: "settings", element: <SettingsPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
  {
    path: "/login",
    element: (
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    ),
  },
  {
    path: "/register",
    element: (
      <AuthProvider>
        <RegisterPage />
      </AuthProvider>
    ),
  },
  { path: "/legacy", element: <Navigate to="/" replace /> },
]);
