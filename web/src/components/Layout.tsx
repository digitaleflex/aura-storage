import { Link, useNavigate } from "@tanstack/react-router";
import { useAuth } from "../lib/auth";

export function Layout({ children }: { children: React.ReactNode }) {
  const { csrf, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    await navigate({ to: "/login" });
  }

  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">
          AURA Storage
        </Link>
        <nav className="nav">
          {csrf ? (
            <button type="button" className="btn btn-ghost" onClick={handleLogout}>
              Log out
            </button>
          ) : (
            <Link to="/login" className="btn btn-ghost">
              Log in
            </Link>
          )}
        </nav>
      </header>
      <main className="content">{children}</main>
    </div>
  );
}
