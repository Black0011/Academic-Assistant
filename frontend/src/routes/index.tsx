import { createBrowserRouter, Navigate } from "react-router-dom";

import { AuthProvider } from "@/components/auth/AuthProvider";
import { RequireAuth } from "@/components/auth/RequireAuth";
import { AppLayout } from "@/components/layout/AppLayout";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { DashboardPage } from "@/pages/DashboardPage";
import { KnowledgeLibraryPage } from "@/pages/KnowledgeLibraryPage";
import { LoginPage } from "@/pages/LoginPage";
import { ManuscriptsPage } from "@/pages/ManuscriptsPage";
import { McpServersPage } from "@/pages/McpServersPage";
import { MemoryPage } from "@/pages/MemoryPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { PaperWriterPage } from "@/pages/PaperWriterPage";
import { PlannerPage } from "@/pages/PlannerPage";
import { ProposalsPage } from "@/pages/ProposalsPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { RevisionPage } from "@/pages/RevisionPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SkillsPage } from "@/pages/SkillsPage";
import { TaskDetailPage } from "@/pages/TaskDetailPage";
import { TasksPage } from "@/pages/TasksPage";
import { UnifiedWorkbenchPage } from "@/pages/UnifiedWorkbenchPage";

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
          // Research console → redirect to unified workbench
          { path: "research", element: <Navigate to="/workbench" replace /> },
          { path: "papers", element: <ManuscriptsPage /> },
          { path: "papers/:manuscriptId", element: <PaperWriterPage /> },
          // Unified workbench (research + writing in one conversational surface)
          { path: "workbench", element: <ErrorBoundary><UnifiedWorkbenchPage /></ErrorBoundary> },
          { path: "workbench/:manuscriptId", element: <ErrorBoundary><UnifiedWorkbenchPage /></ErrorBoundary> },
          { path: "chat", element: <Navigate to="/workbench" replace /> },
          { path: "chat/:manuscriptId", element: <Navigate to="/workbench/:manuscriptId" replace /> },
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
