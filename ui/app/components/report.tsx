// portraitist 报告视图页（M3）：复用 NextChat Markdown 渲染链 + 导出按钮
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import LoadingIcon from "../icons/three-dots.svg";
import { useChatStore } from "../store";
import { getPortraitistSessionId, PORTRAITIST_BASE } from "../utils/portraitist";
import styles from "./report.module.scss";

const Markdown = dynamic(async () => (await import("./markdown")).Markdown, {
  loading: () => <LoadingIcon />,
});

interface ReportData {
  markdown: string;
  checks?: { ok?: boolean; warnings?: string[] };
  generated_at?: string;
}

export function ReportPage() {
  const navigate = useNavigate();
  const session = useChatStore((state) => state.currentSession());
  const [data, setData] = useState<ReportData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const sid = getPortraitistSessionId(session.id);
    if (!sid) {
      setError("该会话尚未绑定后端（可能是未进行过访谈的本地会话）");
      return;
    }
    fetch(`${PORTRAITIST_BASE}/api/sessions/${sid}/report`)
      .then((r) =>
        r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)),
      )
      .then((d) => setData(d))
      .catch((e) => setError(`报告获取失败: ${e.message}`));
  }, [session.id]);

  const exportMd = () => {
    if (!data) return;
    const blob = new Blob([data.markdown], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `portraitist-报告-${session.topic || "未命名"}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <button className={styles.back} onClick={() => navigate(-1)}>
          ← 返回
        </button>
        <h2>心理画像报告</h2>
        <button className={styles.export} onClick={exportMd} disabled={!data}>
          导出 Markdown
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {!data && !error && <div className={styles.loading}>加载中…</div>}

      {data && (
        <>
          <div className={styles.meta}>
            <span>生成时间: {data.generated_at || "-"}</span>
            <span>校验: {data.checks?.ok ? "✅ 通过" : "⚠️ 未通过"}</span>
          </div>
          <div className={styles.markdown}>
            <Markdown content={data.markdown} />
          </div>
        </>
      )}
    </div>
  );
}
