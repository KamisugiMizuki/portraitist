// portraitist 会话详情页：显示后端 session 的 transcript 全量原文
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useChatStore } from "../store";
import { getPortraitistSessionId } from "../utils/portraitist";
import { IconButton } from "./button";
import { Avatar } from "./emoji";
import styles from "./session-view.module.scss";

const PORTRAITIST_BASE = "http://127.0.0.1:8000";

interface TranscriptMsg {
  role: string;
  content: string;
  kind?: string;
}

interface SessionDetail {
  session_id: string;
  status: string;
  rounds: number;
  transcript: TranscriptMsg[];
  report: { path?: string; checks?: { ok?: boolean } } | null;
  coverage?: {
    saturated_count?: number;
    dimension_total?: number;
    unresolved_contradictions?: number;
  };
}

export function SessionView() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionId) return;
    let alive = true;
    fetch(`${PORTRAITIST_BASE}/api/sessions/${sessionId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: SessionDetail) => alive && setDetail(d))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [sessionId]);

  if (error) return <div className={styles.error}>加载失败：{error}</div>;
  if (!detail) return <div className={styles.error}>加载中…</div>;

  const dimCount = detail.coverage?.saturated_count ?? 0;
  const dimTotal = detail.coverage?.dimension_total ?? 11;
  const unresolved = detail.coverage?.unresolved_contradictions ?? 0;

  const continueChat = () => {
    // 绑定到本地会话继续访谈（active 会话）
    const chatStore = useChatStore.getState();
    chatStore.newSession();
    const session = chatStore.currentSession();
    localStorage.setItem(
      `portraitist:session-map:${session.id}`,
      detail!.session_id,
    );
    navigate("/chat");
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <IconButton
          icon={<span>←</span>}
          bordered
          title="返回"
          onClick={() => navigate("/")}
        />
        <div className={styles.meta}>
          <div className={styles.title}>
            会话 {detail.session_id.slice(0, 8)}
            <span className={`${styles.badge} ${styles[detail.status]}`}>
              {detail.status}
            </span>
          </div>
          <div className={styles.sub}>
            {detail.rounds} 轮 · 维度饱和 {dimCount}/{dimTotal}
            {unresolved > 0 ? ` · 未闭环矛盾 ${unresolved}` : ""} ·{" "}
            {new Date().toLocaleDateString()}
          </div>
        </div>
        <div className={styles.actions}>
          {(detail.status === "active" || detail.status === "confirming") && (
            <IconButton
              text="继续访谈"
              type="primary"
              onClick={continueChat}
            />
          )}
          {detail.status === "completed" && (
            <IconButton
              text="查看报告"
              type="primary"
              onClick={() => navigate(`/report?sid=${detail!.session_id}`)}
            />
          )}
          <IconButton
            text="打开目录"
            bordered
            onClick={async () => {
              try {
                await fetch(
                  `${PORTRAITIST_BASE}/api/sessions/${detail!.session_id}/open`,
                  { method: "POST" },
                );
              } catch {
                // 打开失败静默（本地工具）
              }
            }}
          />
        </div>
      </div>

      <div className={styles.messages}>
        {detail.transcript.map((m, i) => (
          <div
            key={i}
            className={`${styles.msg} ${m.role === "user" ? styles.user : styles.assistant}`}
          >
            <Avatar avatar={m.role === "user" ? "🧑" : "🧭"} />
            <div className={styles.body}>
              <div className={styles.role}>
                {m.role === "user" ? "你" : "引导师"}
                {m.kind === "invitation" && (
                  <span className={styles.kind}>开场白</span>
                )}
              </div>
              <div className={styles.content}>{m.content}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
