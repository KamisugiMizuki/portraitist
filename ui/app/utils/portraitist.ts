import type { RequestMessage } from "../client/api";

// portraitist 后端会话映射（M3 接线）
//
// NextChat 会话（本地 nanoid）↔ portraitist 后端会话（服务端证据库）映射：
// - 首次发送时调 POST /api/sessions 创建，把开场白作为欢迎消息插入聊天
// - 后续请求在 messages 头部注入 system 标记 "[portraitist-session: <id>]"
//   （标记只进请求体，不落 session.messages，避免重复发送/显示）
// 映射存 localStorage，键 = 本地会话 id，值 = 后端会话 id。

export const PORTRAITIST_BASE = "http://127.0.0.1:8000";
const MAP_KEY = "portraitist:session-map";

function map(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(MAP_KEY) || "{}");
  } catch {
    return {};
  }
}

function save(m: Record<string, string>) {
  localStorage.setItem(MAP_KEY, JSON.stringify(m));
}

export function getPortraitistSessionId(localSessionId: string): string {
  return map()[localSessionId] || "";
}

export function clearPortraitistSession(localSessionId: string) {
  const m = map();
  delete m[localSessionId];
  save(m);
}

/** 确保本地会话已绑定后端会话；未绑定时创建并返回欢迎文本（无则空串）。 */
export async function ensurePortraitistSession(
  localSessionId: string,
): Promise<string> {
  const existing = getPortraitistSessionId(localSessionId);
  if (existing) return "";

  const resp = await fetch(`${PORTRAITIST_BASE}/api/sessions`, {
    method: "POST",
  });
  if (!resp.ok) throw new Error(`创建会话失败: ${resp.status}`);
  const data = await resp.json();
  const m = map();
  m[localSessionId] = data.session_id;
  save(m);
  return data.text || "";
}

/** 拉取全部后端会话状态，按本地会话 id 映射（无映射的本地会话返回空）。 */
export async function fetchStatuses(): Promise<Record<string, string>> {
  try {
    const resp = await fetch(`${PORTRAITIST_BASE}/api/sessions`);
    if (!resp.ok) return {};
    const data = await resp.json();
    const m = map();
    const out: Record<string, string> = {};
    for (const s of data.sessions || []) {
      for (const [localId, sid] of Object.entries(m)) {
        if (sid === s.session_id) out[localId] = s.status;
      }
    }
    return out;
  } catch {
    return {};
  }
}

/** 请求体注入 system 标记；未绑定时返回原数组（发送前应已 ensure）。 */
export function injectSessionTag(
  messages: RequestMessage[],
  localSessionId: string,
): RequestMessage[] {
  const sid = getPortraitistSessionId(localSessionId);
  if (!sid) return messages;
  return [
    { role: "system", content: `[portraitist-session: ${sid}]` },
    ...messages,
  ];
}
