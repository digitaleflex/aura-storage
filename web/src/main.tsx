import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { router } from "./router";
import "./styles.css";
// Component styles introduced by #92 (preview modal, workspace) reference the
// `--vault-*` tokens defined here. `vault-shell.css` (the competing app shell)
// is intentionally NOT imported: main's UI v2 shell (`.shell`) wins.
import "./vault-tokens.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 15_000 },
  },
});

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Missing #root element.");
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
