import { BrowserRouter, Routes, Route, Link, useLocation } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { Admin } from "./pages/Admin";
import { Flame, Settings } from "lucide-react";

function Navigation() {
  const location = useLocation();
  const isActive = (path: string) => location.pathname === path;

  return (
    <nav className="fixed top-0 w-full z-50 bg-[#111]/80 backdrop-blur-xl border-b border-zinc-800/80">
      <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-indigo-500 flex items-center justify-center">
            <Flame className="w-4 h-4 text-white" />
          </div>
          <span className="text-[1.05rem] font-bold text-white tracking-tight">Paygles</span>
        </Link>

        <div className="flex items-center gap-1 bg-zinc-800/60 rounded-full p-1 border border-zinc-700/50">
          <Link
            to="/"
            className={`px-4 py-1.5 rounded-full text-[0.8rem] font-medium transition-all ${isActive("/")
                ? "bg-zinc-700 text-white shadow-sm"
                : "text-zinc-400 hover:text-zinc-200"
              }`}
          >
            Deals
          </Link>
          <Link
            to="/admin"
            className={`px-4 py-1.5 rounded-full text-[0.8rem] font-medium transition-all flex items-center gap-1.5 ${isActive("/admin")
                ? "bg-zinc-700 text-white shadow-sm"
                : "text-zinc-400 hover:text-zinc-200"
              }`}
          >
            <Settings className="w-3.5 h-3.5" />
            Admin
          </Link>
        </div>
      </div>
    </nav>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-[#111]">
        <Navigation />
        <main className="pt-20 pb-16 px-6 max-w-7xl mx-auto">
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
