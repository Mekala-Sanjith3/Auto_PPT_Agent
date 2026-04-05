import { useState, useRef, useEffect } from 'react'
import {
  Play, CheckCircle, Download, Presentation, Loader,
  FileText, Search, BrainCircuit, Activity, Check,
  CircleAlert, FolderOpen, FolderCheck, AlertCircle
} from 'lucide-react'
import './index.css'

function App() {
  const [prompt, setPrompt]         = useState("")
  const [theme, setTheme]           = useState("napkin")
  const [status, setStatus]         = useState("idle")
  const [logs, setLogs]             = useState([])
  const [plan, setPlan]             = useState(null)
  const [filename, setFilename]     = useState(null)
  const [activeSlide, setActiveSlide] = useState(-1)

  const [saveDir, setSaveDir]           = useState("")
  const [saveState, setSaveState]       = useState("idle")
  const [saveFeedback, setSaveFeedback] = useState("")

  const wsRef      = useRef(null)
  const logsEndRef = useRef(null)
  const statusRef  = useRef(status)

  // Keep statusRef in sync so the ws.onclose handler doesn't read a stale value
  useEffect(() => { statusRef.current = status }, [status])

  const handleStart = () => {
    if (!prompt.trim()) return

    setLogs([])
    setPlan(null)
    setFilename(null)
    setActiveSlide(-1)
    setSaveState("idle")
    setSaveFeedback("")
    setStatus("running")

    const ws = new WebSocket("ws://localhost:8000/ws")
    wsRef.current = ws

    ws.onopen = () => ws.send(JSON.stringify({ prompt, theme }))

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      const now  = new Date().toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      })

      if (data.type === "status" || data.type === "progress") {
        setLogs(p => [...p, { time: now, msg: data.message, type: data.type }])
      } else if (data.type === "slide_active") {
        setActiveSlide(data.index)
      } else if (data.type === "plan") {
        setPlan(data.slides)
        setLogs(p => [...p, { time: now, msg: "Slide outline ready.", type: "success" }])
      } else if (data.type === "done") {
        setFilename(data.file)
        setStatus("complete")
        setActiveSlide(-1)
        ws.close()
      } else if (data.type === "error") {
        setLogs(p => [...p, { time: now, msg: data.message, type: "error" }])
        setStatus("error")
        ws.close()
      }
    }

    ws.onerror = () => {
      setStatus("error")
      setLogs(p => [...p, {
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        msg: "WebSocket error — is the backend running?",
        type: "error"
      }])
    }

    ws.onclose = () => {
      if (statusRef.current === "running") setStatus("idle")
    }
  }

  const handleSaveToFolder = async () => {
    if (!filename || !saveDir.trim()) return
    setSaveState("saving")
    setSaveFeedback("")

    try {
      const res  = await fetch("http://localhost:8000/save-to-folder", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ filename, target_dir: saveDir.trim() }),
      })
      const body = await res.json()

      if (body.success) {
        setSaveState("saved")
        setSaveFeedback(`Saved to: ${body.saved_to}`)
      } else {
        setSaveState("error")
        setSaveFeedback(body.error || "Unknown error.")
      }
    } catch {
      setSaveState("error")
      setSaveFeedback("Could not reach backend.")
    }
  }

  // Auto-scroll the log window as new entries appear
  useEffect(() => {
    if (logsEndRef.current) logsEndRef.current.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const THEMES = [
    { id: "napkin",  label: "Napkin"    },
    { id: "ocean",   label: "Ocean"     },
    { id: "dark",    label: "Dark Mode" },
    { id: "minimal", label: "Minimal"   },
  ]

  return (
    <div className="app-container">

      <header className="header">
        <div className="header-icon-wrapper">
          <Presentation className="logo-icon" size={28} />
        </div>
        <div>
          <h1>Auto-PPT Agent</h1>
        </div>
        <p>
          MCP Architecture
          <span className="badge">v5.0</span>
        </p>
      </header>

      <div className="controls-card">
        <div className="input-wrapper">
          <input
            className="prompt-input"
            type="text"
            placeholder="E.g., Create a 10-slide presentation on quantum computing..."
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            disabled={status === "running"}
            onKeyDown={e => e.key === 'Enter' && handleStart()}
          />
          <button
            className={`start-btn ${status === "running" ? "running" : ""}`}
            onClick={handleStart}
            disabled={status === "running" || !prompt.trim()}
          >
            {status === "running"
              ? <Loader className="spin" size={20} />
              : <Play size={20} fill="currentColor" />}
            <span>{status === "running" ? "Processing..." : "Generate Deck"}</span>
          </button>
        </div>

        <div className="theme-selector">
          <span className="theme-label">Visual Theme:</span>
          <div className="theme-pills">
            {THEMES.map(t => (
              <button
                key={t.id}
                className={`theme-pill ${theme === t.id ? 'active' : ''}`}
                onClick={() => setTheme(t.id)}
                disabled={status === "running"}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <main className="dashboard">

        <section className="panel log-panel">
          <div className="panel-header">
            <BrainCircuit size={18} />
            <h3>Agent Execution Stream</h3>
          </div>
          <div className="log-window">
            {logs.length === 0 && (
              <div className="empty-state">System idle. Ready for your prompt.</div>
            )}
            {logs.map((L, i) => (
              <div key={i} className={`log-entry ${L.type}`}>
                <span className="time">[{L.time}]</span>
                <span className="msg">{L.msg}</span>
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </section>

        <section className="panel outline-panel">
          <div className="panel-header">
            <FileText size={18} />
            <h3>Slide Plan &amp; Assets</h3>
          </div>

          <div className="plan-window">
            {!plan && status !== "running" && (
              <div className="empty-state">No outline generated yet.</div>
            )}
            {!plan && status === "running" && (
              <div className="loading-state fade-in">
                <Search className="pulse" size={32} />
                <span>Agent is drafting slide structure...</span>
              </div>
            )}
            {plan && (
              <ul className="slide-list fade-in">
                {plan.map((title, i) => {
                  const isActive = activeSlide === i
                  const isDone   = activeSlide > i || status === "complete"
                  return (
                    <li key={i} className={`slide-item ${isActive ? "active" : ""} ${isDone ? "done" : ""}`}>
                      <div className="slide-number">{i + 1}</div>
                      <div className="slide-title">{title}</div>
                      <div className="slide-status-icon">
                        {isActive && <Activity size={16} className="spin" style={{ animationDuration: '2s' }} />}
                        {isDone   && <Check size={16} />}
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          {status === "complete" && filename && (
            <div className="result-section fade-in">

              <div className="download-row">
                <CheckCircle className="success-icon" size={26} />
                <div className="file-info">
                  <strong>Slide Deck Ready!</strong>
                  <span>{filename}</span>
                </div>
                <a
                  href={`http://localhost:8000/download/${filename}`}
                  className="download-btn"
                  target="_blank"
                  download
                >
                  <Download size={16} /> Download
                </a>
              </div>

              <div className="result-divider" />

              <div className="save-folder-row">
                <div className="save-folder-label">
                  <FolderOpen size={15} />
                  <span>Also save to a folder on this PC:</span>
                </div>
                <div className="save-folder-input-group">
                  <input
                    className="folder-input"
                    type="text"
                    placeholder="e.g. C:/Users/Sanjith/Desktop/Presentations"
                    value={saveDir}
                    onChange={e => {
                      setSaveDir(e.target.value)
                      setSaveState("idle")
                      setSaveFeedback("")
                    }}
                    disabled={saveState === "saving"}
                  />
                  <button
                    className={`save-folder-btn ${saveState}`}
                    onClick={handleSaveToFolder}
                    disabled={!saveDir.trim() || saveState === "saving"}
                  >
                    {saveState === "saving" && <Loader className="spin" size={15} />}
                    {saveState === "saved"  && <FolderCheck size={15} />}
                    {saveState === "error"  && <AlertCircle size={15} />}
                    {saveState === "idle"   && <FolderOpen size={15} />}
                    <span>
                      {saveState === "saving" ? "Saving..."
                        : saveState === "saved"  ? "Saved!"
                        : saveState === "error"  ? "Retry"
                        : "Save to Folder"}
                    </span>
                  </button>
                </div>
                {saveFeedback && (
                  <p className={`save-feedback ${saveState}`}>{saveFeedback}</p>
                )}
              </div>

            </div>
          )}

          {status === "error" && (
            <div className="error-section fade-in">
              <CircleAlert size={22} />
              <span>Agent encountered an error. Check the execution stream.</span>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}

export default App
