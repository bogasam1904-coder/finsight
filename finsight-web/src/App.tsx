import { useState } from "react";

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState("");
  const [loading, setLoading] = useState(false);

  const API_URL = import.meta.env.VITE_API_URL;

  const handleUpload = async () => {
    if (!file) {
      alert("Please select a file");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    setLoading(true);
    setResult("");

    try {
      const res = await fetch(`${API_URL}/api/analyze`, {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      setResult(data.analysis || "No response from AI");
    } catch (err) {
      console.error(err);
      setResult("Error connecting to backend");
    }

    setLoading(false);
  };

  return (
    <div style={{ padding: 40, fontFamily: "Arial" }}>
      <h1>📊 Finsight AI</h1>
      <p>Upload financial statements and get AI analysis</p>

      <input
        type="file"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
      />

      <br />
      <br />

      <button onClick={handleUpload} disabled={loading}>
        {loading ? "Analyzing..." : "Analyze Financials"}
      </button>

      <div style={{ marginTop: 30, whiteSpace: "pre-wrap" }}>
        {result}
      </div>
    </div>
  );
}

