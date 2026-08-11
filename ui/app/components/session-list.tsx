// portraitist 会话列表：后端 sessions/ 全量（替代 NextChat 本地会话列表）
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import styles from "./session-list.module.scss";

const PORTRAITIST_BASE = "http://127.0.0.1:8000";

export interface BackendSession {
  session_id: string;
  status: string;
  rounds: number;
  created_at: string;
  title: string;
  has_report: boolean;
  report_ok: boolean;
}

const STATUS_TEXT: Record<string, string> = {
  active: "进行中",
  confirming: "确认中",
  completed: "已完成",
};

export function SessionList(props: { narrow?: boolean }) {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<BackendSession[]>([]);
  const [error, setError] = useState(false);

  const load = async () => {
    try {
      const resp = await fetch(`${PORTRAITIST_BASE}/api/sessions`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setSessions(data.sessions ?? []);
      setError(false);
    } catch {
      setError(true);
    }
  };

  useEffect(() => {
    let alive = true;
    const safeLoad = async () => {
      try {
        const resp = await fetch(`${PORTRAITIST_BASE}/api/sessions`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (alive) {
          setSessions(data.sessions ?? []);
          setError(false);
        }
      } catch {
        if (alive) setError(true);
      }
    };
    safeLoad();
    const timer = setInterval(safeLoad, 30000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const removeSession = async (sid: string) => {
    if (!window.confirm(`删除会话 ${sid.slice(0, 8)}？（本地文件将一并删除）`))
      return;
    try {
      const resp = await fetch(
        `${PORTRAITIST_BASE}/api/sessions/${sid}`,
        { method: "DELETE" },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await load();
    } catch {
      window.alert("删除失败：后端未连接或会话不存在");
    }
  };

  if (error) {
    return (
      <div className={styles.empty}>后端未连接（127.0.0.1:8000）</div>
    );
  }
  if (sessions.length === 0) {
    return <div className={styles.empty}>暂无历史会话</div>;
  }

  return (
    <div className={styles.list}>
      {sessions.map((s) => (
        <div
          key={s.session_id}
          className={styles.item}
          onClick={() => navigate(`/session/${s.session_id}`)}
          title={s.session_id}
        >
          <div className={styles.itemTitle}>
            <span className={styles.dot} data-status={s.status} />
            <span className={styles.itemTitleText}>
              {s.title || s.session_id.slice(0, 12)}
            </span>
            <span
              className={styles.deleteBtn}
              role="button"
              title="删除会话"
              onClick={(e) => {
                e.stopPropagation();
                removeSession(s.session_id);
              }}
            >
              🗑
            </span>
          </div>
          <div className={styles.itemMeta}>
            {STATUS_TEXT[s.status] ?? s.status} · {s.rounds} 轮
            {s.has_report && (
              <span
                className={styles.report}
                onClick={(e) => {
                  e.stopPropagation();
                  navigate(`/report?sid=${s.session_id}`);
                }}
              >
                📄 报告
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
