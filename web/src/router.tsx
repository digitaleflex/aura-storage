import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router";
import { Layout } from "./components/Layout";
import { AuthProvider, RequireAuth } from "./lib/auth";
import { FolderProvider } from "./lib/folderContext";
import { LoginPage } from "./pages/LoginPage";
import { ObjectsPage } from "./pages/ObjectsPage";
import { TransfersPage } from "./pages/TransfersPage";
import { DashboardPage } from "./pages/DashboardPage";
import { SharesPage } from "./pages/SharesPage";
import { TrashPage } from "./pages/TrashPage";
import { SettingsPage } from "./pages/SettingsPage";
import { lazy, Suspense } from "react";
import { Loading } from "./components/Loading";
import { RouteError } from "./components/RouteError";
import { TransfersProvider } from "./lib/transferContext";

const AdminPage = lazy(() => import("./pages/AdminPage").then((m) => ({ default: m.AdminPage })));
const DiagPage = lazy(() => import("./pages/DiagPage").then((m) => ({ default: m.DiagPage })));

const rootRoute = createRootRoute({
  component: () => (
    <AuthProvider>
      <FolderProvider>
        <TransfersProvider>
          <Outlet />
        </TransfersProvider>
      </FolderProvider>
    </AuthProvider>
  ),
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: () => (
    <Layout>
      <RequireAuth>
        <ObjectsPage />
      </RequireAuth>
    </Layout>
  ),
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginPage,
});

const adminRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin",
  component: () => (
    <Layout>
      <RequireAuth>
        <Suspense fallback={<Loading label="Chargement de l'administration" />}>
          <AdminPage />
        </Suspense>
      </RequireAuth>
    </Layout>
  ),
});

const transfersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/transfers",
  component: () => (
    <Layout>
      <RequireAuth>
        <TransfersPage />
      </RequireAuth>
    </Layout>
  ),
});

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/dashboard",
  component: () => (
    <Layout>
      <RequireAuth>
        <DashboardPage />
      </RequireAuth>
    </Layout>
  ),
});

const sharesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/shares",
  component: () => (
    <Layout>
      <RequireAuth>
        <SharesPage />
      </RequireAuth>
    </Layout>
  ),
});

const trashRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/trash",
  component: () => (
    <Layout>
      <RequireAuth>
        <TrashPage />
      </RequireAuth>
    </Layout>
  ),
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: () => (
    <Layout>
      <RequireAuth>
        <SettingsPage />
      </RequireAuth>
    </Layout>
  ),
});

const diagRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/diagnostic",
  component: () => (
    <Layout>
      <RequireAuth>
        <Suspense fallback={<Loading label="Chargement du diagnostic" />}>
          <DiagPage />
        </Suspense>
      </RequireAuth>
    </Layout>
  ),
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  loginRoute,
  adminRoute,
  transfersRoute,
  dashboardRoute,
  sharesRoute,
  trashRoute,
  settingsRoute,
  diagRoute,
]);

// Same subpath as Vite base (dev "/app", prod "/app", unset = root).
const basepath = import.meta.env.VITE_SUBPATH
  ? `/${import.meta.env.VITE_SUBPATH.replace(/^\//, "").replace(/\/$/, "")}`
  : undefined;

export const router = createRouter({
  routeTree,
  basepath,
  defaultErrorComponent: ({ error }) => <RouteError error={error} />,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
