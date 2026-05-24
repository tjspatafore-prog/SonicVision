import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import AppHeader from "@/components/AppHeader";
import Dashboard from "@/pages/Dashboard";
import NewProject from "@/pages/NewProject";
import Editor from "@/pages/Editor";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AppHeader />
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<NewProject />} />
          <Route path="/editor/:id" element={<Editor />} />
        </Routes>
        <Toaster theme="dark" position="bottom-right" richColors />
      </BrowserRouter>
    </div>
  );
}

export default App;
