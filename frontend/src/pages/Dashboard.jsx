import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listProjects, deleteProject, fileUrl } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Film, Loader2, Trash2, Music, AlertCircle, Ban } from "lucide-react";

const DASHBOARD_HERO =
  "https://static.prod-images.emergentagent.com/jobs/b1634619-17f6-41f0-9331-7b878bd81c04/images/7c013a93c3b29452c958b7151667b8c5fff46ccab1f9d68347a33cf520e6e901.png";

function statusMeta(s) {
  const map = {
    created: { label: "Queued", color: "text-zinc-400" },
    transcribing: { label: "Transcribing", color: "text-amber-400" },
    generating_images: { label: "Generating Scenes", color: "text-amber-400" },
    rendering: { label: "Rendering", color: "text-amber-400" },
    completed: { label: "Ready", color: "text-emerald-400" },
    failed: { label: "Failed", color: "text-rose-400" },
    cancelled: { label: "Cancelled", color: "text-zinc-500" },
  };
  return map[s] || { label: s, color: "text-zinc-400" };
}

export default function Dashboard() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const refresh = async () => {
    try {
      const data = await listProjects();
      setProjects(data);
    } catch (e) {
      toast.error("Failed to load projects");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 3500);
    return () => clearInterval(interval);
  }, []);

  const handleDelete = async (id, e) => {
    e.stopPropagation();
    e.preventDefault();
    if (!window.confirm("Delete this project?")) return;
    try {
      await deleteProject(id);
      toast.success("Project deleted");
      refresh();
    } catch {
      toast.error("Delete failed");
    }
  };

  return (
    <div className="max-w-[1400px] mx-auto px-6 md:px-10 py-10">
      {/* Hero */}
      <section
        data-testid="dashboard-hero"
        className="relative overflow-hidden rounded-md border border-zinc-800 mb-12"
        style={{ height: 300 }}
      >
        <img
          src={DASHBOARD_HERO}
          alt=""
          className="absolute inset-0 w-full h-full object-cover opacity-50"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-black via-black/70 to-transparent" />
        <div className="relative h-full flex flex-col justify-center px-8 md:px-14 max-w-2xl">
          <span className="label-tracking text-amber-500 mb-3">SonicVision</span>
          <h1
            className="text-4xl sm:text-5xl font-light tracking-tight mb-3 text-zinc-50"
            style={{ fontFamily: "Outfit" }}
          >
            Turn songs into cinematic music videos.
          </h1>
          <p className="text-sm text-zinc-400 mb-6 max-w-md leading-relaxed">
            Drop an audio file. We transcribe every lyric, paint a scene for each phrase,
            then render a Ken-Burns music video — perfectly timed.
          </p>
          <button
            onClick={() => navigate("/new")}
            data-testid="hero-new-project-btn"
            className="self-start inline-flex items-center gap-2 px-5 py-3 rounded bg-amber-500 hover:bg-amber-400 text-black font-medium transition-colors"
          >
            <Plus className="w-4 h-4" /> Start a new video
          </button>
        </div>
      </section>

      {/* Projects */}
      <div className="flex items-baseline justify-between mb-6">
        <h2 className="text-2xl font-normal tracking-tight" style={{ fontFamily: "Outfit" }}>
          Your projects
        </h2>
        <span className="label-tracking">{projects.length} total</span>
      </div>

      {loading ? (
        <div className="flex items-center gap-3 text-zinc-500 py-12">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading...
        </div>
      ) : projects.length === 0 ? (
        <div
          data-testid="empty-state"
          className="border border-dashed border-zinc-800 rounded-md p-12 text-center"
        >
          <Film className="w-10 h-10 mx-auto text-zinc-700 mb-4" />
          <p className="text-zinc-400 mb-4">No projects yet. Make your first music video.</p>
          <Link
            to="/new"
            data-testid="empty-new-link"
            className="inline-flex items-center gap-2 px-4 py-2 rounded bg-amber-500 text-black font-medium hover:bg-amber-400"
          >
            <Plus className="w-4 h-4" /> Create project
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {projects.map((p) => {
            const meta = statusMeta(p.status);
            const firstSceneImg = p.scenes?.find((s) => s.image_filename)?.image_filename;
            const thumb = firstSceneImg ? fileUrl(p.id, firstSceneImg) : null;
            const isVertical = p.aspect_ratio === "9:16";
            return (
              <Link
                key={p.id}
                to={`/editor/${p.id}`}
                data-testid={`project-card-${p.id}`}
                className="group block border border-zinc-800 hover:border-amber-500/60 bg-[#141414] rounded-md overflow-hidden transition-colors"
              >
                <div
                  className="relative bg-[#0f0f0f] overflow-hidden"
                  style={{ aspectRatio: isVertical ? "9 / 16" : "16 / 9" }}
                >
                  {thumb ? (
                    <img
                      src={thumb}
                      alt={p.name}
                      className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-zinc-700">
                      <Music className="w-10 h-10" />
                    </div>
                  )}
                  {p.status !== "completed" &&
                    p.status !== "failed" &&
                    p.status !== "cancelled" && (
                      <div className="absolute bottom-0 left-0 right-0 h-1 bg-zinc-900">
                        <div
                          className="h-full bg-amber-500 transition-all"
                          style={{ width: `${p.progress || 0}%` }}
                        />
                      </div>
                    )}
                  <div className="absolute top-2 left-2">
                    <span className="text-[10px] px-2 py-0.5 rounded bg-black/70 border border-zinc-700 text-zinc-300 font-mono tabular-nums">
                      {p.aspect_ratio} · {p.resolution || "720p"}
                    </span>
                  </div>
                </div>
                <div className="p-4">
                  <div className="flex items-start justify-between mb-1 gap-2">
                    <h3
                      className="text-base font-medium tracking-tight truncate text-zinc-100"
                      style={{ fontFamily: "Outfit" }}
                    >
                      {p.name}
                    </h3>
                    <button
                      onClick={(e) => handleDelete(p.id, e)}
                      data-testid={`delete-project-${p.id}`}
                      className="p-1 text-zinc-600 hover:text-rose-400 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                  <div className={`flex items-center gap-2 text-xs ${meta.color}`}>
                    {p.status === "failed" ? (
                      <AlertCircle className="w-3 h-3" />
                    ) : p.status === "completed" ? (
                      <Film className="w-3 h-3" />
                    ) : p.status === "cancelled" ? (
                      <Ban className="w-3 h-3" />
                    ) : (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    )}
                    <span className="label-tracking">{meta.label}</span>
                    <span className="text-zinc-600">·</span>
                    <span className="text-zinc-500 normal-case tracking-normal">
                      {p.scenes?.length || 0} scenes
                    </span>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
