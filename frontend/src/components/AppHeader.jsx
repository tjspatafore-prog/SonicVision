import { Link, useLocation } from "react-router-dom";
import { Disc3 } from "lucide-react";

export default function AppHeader() {
  const loc = useLocation();
  return (
    <header
      data-testid="app-header"
      className="sticky top-0 z-50 backdrop-blur-xl bg-black/70 border-b border-white/10"
    >
      <div className="max-w-[1400px] mx-auto px-6 md:px-10 h-16 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-3" data-testid="nav-home-link">
          <div className="w-9 h-9 rounded-md bg-gradient-to-br from-amber-500 to-amber-700 flex items-center justify-center">
            <Disc3 className="w-5 h-5 text-black" strokeWidth={2.4} />
          </div>
          <div className="flex flex-col leading-tight">
            <span
              className="text-base font-medium tracking-tight"
              style={{ fontFamily: "Outfit" }}
            >
              SonicVision
            </span>
            <span className="label-tracking text-[10px]">AI Music Video Forge</span>
          </div>
        </Link>
        <nav className="flex items-center gap-6">
          <Link
            to="/"
            data-testid="nav-projects-link"
            className={`text-sm transition-colors ${
              loc.pathname === "/" ? "text-amber-500" : "text-zinc-400 hover:text-zinc-100"
            }`}
          >
            Projects
          </Link>
          <Link
            to="/new"
            data-testid="nav-new-link"
            className="text-sm px-4 py-2 rounded bg-amber-500 text-black font-medium hover:bg-amber-400 transition-colors"
          >
            New Project
          </Link>
        </nav>
      </div>
    </header>
  );
}
