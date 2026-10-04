import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;
export const api = axios.create({ baseURL: API });

export const fileUrl = (projectId, filename) =>
  `${API}/files/${projectId}/${filename}`;

export const audioUrl = (projectId) =>
  `${API}/projects/${projectId}/audio`;

export const downloadVideoUrl = (projectId) =>
  `${API}/projects/${projectId}/video`;

export const downloadSrtUrl = (projectId) =>
  `${API}/projects/${projectId}/srt`;

export const teaserUrl = (projectId, ratio /* "9:16" | "1:1" */) =>
  `${API}/projects/${projectId}/teaser/${ratio.replace(":", "-")}`;

export const listProjects = () => api.get("/projects").then((r) => r.data);
export const getProject = (id) => api.get(`/projects/${id}`).then((r) => r.data);
export const createProject = (formData) =>
  api.post("/projects", formData, { headers: { "Content-Type": "multipart/form-data" } }).then((r) => r.data);
export const createProjectFromUrl = (body) =>
  api.post("/projects/from-url", body).then((r) => r.data);
export const deleteProject = (id) => api.delete(`/projects/${id}`).then((r) => r.data);

export const regenerateScene = (projectId, sceneIdx, imageIdx = 0) =>
  api.post(`/projects/${projectId}/scenes/${sceneIdx}/regenerate-image`, null, { params: { image_idx: imageIdx } })
     .then((r) => r.data);

export const updateOverlay = (projectId, overlay) =>
  api.put(`/projects/${projectId}/overlay`, overlay).then((r) => r.data);

export const triggerRender = (projectId) =>
  api.post(`/projects/${projectId}/render`).then((r) => r.data);

export const updateScene = (projectId, idx, body) =>
  api.patch(`/projects/${projectId}/scenes/${idx}`, body).then((r) => r.data);

export const cancelProject = (projectId) =>
  api.post(`/projects/${projectId}/cancel`).then((r) => r.data);

export const setBurnSubtitles = (projectId, on) =>
  api.put(`/projects/${projectId}/burn-subtitles`, { burn_subtitles: on }).then((r) => r.data);

export const triggerTeaser = (projectId) =>
  api.post(`/projects/${projectId}/teaser`).then((r) => r.data);

export const listFonts = () => api.get("/fonts").then((r) => r.data);
