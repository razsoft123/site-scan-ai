import { useEffect } from "react";
import { AuthScreen } from "./components/AuthScreen";
import { Dashboard } from "./components/Dashboard";
import { useAuthStore } from "./stores/auth-store";

function LoadingScreen() {
  return (
    <main className="grid min-h-screen place-items-center bg-[var(--canvas)] px-6">
      <div className="flex items-center gap-3 text-sm text-[var(--muted)]" role="status">
        <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-[var(--accent)]" />
        Restoring your workspace
      </div>
    </main>
  );
}

export default function App() {
  const user = useAuthStore((state) => state.user);
  const initialized = useAuthStore((state) => state.initialized);
  const initialize = useAuthStore((state) => state.initialize);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  if (!initialized) return <LoadingScreen />;
  return user ? <Dashboard /> : <AuthScreen />;
}
