import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Link, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { Dashboard } from "./pages/Dashboard";
import { Admin } from "./pages/Admin";
import { MoonStar, Radar, Settings2, Sun, Tag } from "lucide-react";

type ThemeMode = "light" | "dark";

function Navigation({
  theme,
  onToggleTheme,
}: {
  theme: ThemeMode;
  onToggleTheme: () => void;
}) {
  const location = useLocation();
  const isActive = (path: string) => location.pathname === path;

  return (
    <nav className="glass-nav fixed top-0 z-50 w-full border-b border-white/50 bg-white/55 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
        <Link to="/" className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-[#102a43] shadow-[0_8px_18px_rgba(16,42,67,0.25)]">
            <Radar className="h-4 w-4 text-amber-300" />
          </div>
          <span className="text-[1.08rem] font-extrabold tracking-tight text-[#102a43] dark:text-slate-100">Paygles</span>
        </Link>

        <div className="flex items-center gap-2">
          <div className="glass-pill flex items-center gap-1 rounded-md border border-[#d9e6f2] bg-white/85 p-1 shadow-[0_8px_24px_rgba(16,42,67,0.12)]">
          <Link
            to="/"
            className={`flex h-8 items-center gap-1.5 rounded px-3 text-xs font-bold transition ${isActive("/")
                ? "bg-[#102a43] text-white"
                : "text-slate-600 hover:bg-slate-100 hover:text-[#102a43]"
              }`}
          >
            <Tag className="h-3.5 w-3.5" />
            Fırsatlar
          </Link>
          <Link
            to="/admin"
            className={`flex h-8 items-center gap-1.5 rounded px-3 text-xs font-bold transition ${isActive("/admin")
                ? "bg-[#102a43] text-white"
                : "text-slate-600 hover:bg-slate-100 hover:text-[#102a43]"
              }`}
          >
            <Settings2 className="h-3.5 w-3.5" />
            Ayarlar
          </Link>
          </div>
          <button
            type="button"
            onClick={onToggleTheme}
            aria-label={theme === "light" ? "Koyu temaya geç" : "Açık temaya geç"}
            title={theme === "light" ? "Koyu tema" : "Açık tema"}
            className="glass-pill inline-flex h-10 w-10 items-center justify-center rounded-md border border-[#d9e6f2] bg-white/85 text-slate-700 shadow-[0_8px_24px_rgba(16,42,67,0.12)] transition hover:text-[#102a43] dark:border-slate-600 dark:bg-slate-900/80 dark:text-slate-200"
          >
            {theme === "light" ? <MoonStar className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </nav>
  );
}

function App() {
  const [theme, setTheme] = useState<ThemeMode>(() => {
    if (typeof window === "undefined") return "light";
    const saved = window.localStorage.getItem("paygles-theme");
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    window.localStorage.setItem("paygles-theme", theme);
  }, [theme]);

  return (
    <BrowserRouter>
      <div className="app-canvas min-h-screen">
        <div className="pointer-events-none fixed inset-0 -z-10">
          <div className="absolute -left-28 -top-20 h-80 w-80 rounded-full bg-[radial-gradient(circle_at_center,rgba(56,189,248,0.24),transparent_65%)] blur-2xl" />
          <div className="absolute right-0 top-24 h-96 w-96 rounded-full bg-[radial-gradient(circle_at_center,rgba(20,184,166,0.20),transparent_70%)] blur-2xl" />
          <div className="absolute bottom-0 left-1/3 h-80 w-80 rounded-full bg-[radial-gradient(circle_at_center,rgba(245,158,11,0.16),transparent_70%)] blur-2xl" />
        </div>
        <Navigation
          theme={theme}
          onToggleTheme={() => setTheme((current) => (current === "light" ? "dark" : "light"))}
        />
        <Toaster
          position="top-right"
          closeButton
          expand
          theme={theme === "dark" ? "dark" : "light"}
        />
        <main className="mx-auto max-w-7xl px-4 pb-16 pt-24 sm:px-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/admin" element={<Admin />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
