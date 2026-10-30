import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Alert, Button, Form, Input, Spin, Typography } from "antd";
import { KeyRound, LogOut } from "lucide-react";
import { request } from "./api/client";

const AccessActor = createContext<string | null>(null);
export const useAuthenticatedActor = () => useContext(AccessActor);

export function AccessGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<any>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    request<any>("/api/access/session", { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) { setSession(value); setError(""); }
    }).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    const expired = () => setSession({ authenticated: false, mode: "SHARED_PASSWORD" });
    window.addEventListener("geo-session-expired", expired);
    return () => { controller.abort(); window.removeEventListener("geo-session-expired", expired); };
  }, [reload]);
  async function login(values: { credential: string }) {
    setBusy(true); setError("");
    try {
      const field = session?.mode === "INVITATION" ? "access_key" : "password";
      await request("/api/access/session", { method: "POST", body: JSON.stringify({ [field]: values.credential }) });
      setReload(n => n + 1);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  if (!session) return <main className="access-panel">{error ? <><Alert type="error" message={error} /><Button onClick={() => setReload(n => n + 1)}>重试连接</Button></> : <Spin tip="连接服务" />} </main>;
  if (!session.authenticated) return <main className="access-panel">
    <Typography.Title level={2}>GEO 项目登录</Typography.Title>
    {error && <Alert type="error" message={error} />}
    <Form layout="vertical" onFinish={login}>
      <Form.Item
        label={session.mode === "INVITATION" ? "访问凭证" : "登录密码"}
        name="credential"
        rules={[{
          required: true,
          min: session.mode === "INVITATION" ? 32 : 12,
          message: session.mode === "INVITATION" ? "请输入管理员提供的访问凭证" : "请输入管理员提供的登录密码",
        }]}
      ><Input.Password autoComplete="current-password" /></Form.Item>
      <Button type="primary" htmlType="submit" loading={busy} icon={<KeyRound size={16} />}>登录</Button>
    </Form>
  </main>;
  return <AccessActor.Provider value={session.name}>{["INVITATION", "SHARED_PASSWORD"].includes(session.mode) && <div className="access-account"><span>{session.name}</span><Button size="small" icon={<LogOut size={14} />} onClick={async () => {
    try { await request("/api/access/session", { method: "DELETE" }); setSession({ authenticated: false, mode: session.mode }); }
    catch (e) { setError((e as Error).message); }
  }}>退出登录</Button>{error && <Alert type="error" message={error} />}</div>}{children}</AccessActor.Provider>;
}
