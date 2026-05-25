import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { i18n } from "@/i18n";
import { router } from "@/routes";
import { queryClient } from "@/lib/queryClient";
import { applyTheme, useUiStore } from "@/stores/uiStore";

import "./index.css";

const initialUi = useUiStore.getState();
applyTheme(initialUi.theme);
// One-time sync: persisted store wins over the language i18n auto-detected
// at module load time. Subsequent setLanguage calls trigger this listener.
if (i18n.language !== initialUi.language) {
  void i18n.changeLanguage(initialUi.language);
}
useUiStore.subscribe((s, prev) => {
  if (s.language !== prev.language && i18n.language !== s.language) {
    void i18n.changeLanguage(s.language);
  }
});

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("missing #root mount node");

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
