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
