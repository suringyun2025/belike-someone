import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./layout";
import { Spinner, ToastProvider } from "./ui";
import { DashboardPage } from "./pages/Dashboard";
import { ProjectsPage } from "./pages/Projects";
import { ProjectWorkspacePage } from "./pages/ProjectWorkspace";
import { ProvidersPage } from "./pages/Providers";
import { SettingsPage } from "./pages/Settings";
import { OpsPage } from "./pages/Ops";
import { LoginPage } from "./pages/Login";
import { SandboxPage } from "./pages/Sandbox";
import { NotFoundPage } from "./pages/NotFound";
import { api } from "./api";
import type { AuthUser } from "./types";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 3000,
    },
  },
});

/**
 * Gate the app behind a session when the server requires one.
 *
 * The decision comes from the server (`/auth/config`): a single-user local build
 * reports `multiuser: false` and renders straight through, so the desktop
 * workflow never sees a login screen. A sandbox instance shows the demo entry
 * instead of a login form — there are no accounts to log into.
 */
function AuthGate({ children }: { children: React.ReactNode }) {
  const config = useQuery({
    queryKey: ["auth-config"],
    queryFn: api.authConfig,
    staleTime: 60_000,
    retry: 0,
  });

  const isSandbox = Boolean(config.data?.sandbox);

  const me = useQuery<AuthUser>({
    queryKey: ["me"],
    queryFn: api.me,
    enabled: Boolean(config.data?.multiuser),
    retry: false,
    staleTime: 30_000,
  });

  if (config.isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  // Server unreachable, or auth is off: the page handles its own errors, and the
  // single-user build renders through below.
  if (!config.isError && !config.data?.multiuser) {
    return <>{children}</>;
  }

  if (me.isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  if (!me.data) {
    return isSandbox ? <SandboxPage /> : <LoginPage />;
  }

  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <AuthGate>
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<DashboardPage />} />
                <Route path="projects" element={<ProjectsPage />} />
                <Route path="projects/:projectId" element={<ProjectWorkspacePage />} />
                <Route path="providers" element={<ProvidersPage />} />
                <Route path="ops" element={<OpsPage />} />
                <Route path="settings" element={<SettingsPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Routes>
          </AuthGate>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}