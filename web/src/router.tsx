import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router";
import { Layout } from "./components/Layout";
import { AuthProvider, RequireAuth } from "./lib/auth";
import { LoginPage } from "./pages/LoginPage";
import { ObjectsPage } from "./pages/ObjectsPage";
import { AdminPage } from "./pages/AdminPage";

const rootRoute = createRootRoute({
  component: () => (
    <AuthProvider>
      <Outlet />
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
        <AdminPage />
      </RequireAuth>
    </Layout>
  ),
});

const routeTree = rootRoute.addChildren([indexRoute, loginRoute, adminRoute]);

// Same subpath as Vite base (dev "/app", prod "/app", unset = root).
const basepath = import.meta.env.VITE_SUBPATH
  ? `/${import.meta.env.VITE_SUBPATH.replace(/^\//, "").replace(/\/$/, "")}`
  : undefined;

export const router = createRouter({ routeTree, basepath });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
