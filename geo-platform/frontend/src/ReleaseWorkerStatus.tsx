import { useEffect, useRef, useState } from "react";
import { Alert, Button, Space, Tag, Tooltip } from "antd";
import { RefreshCw } from "lucide-react";
import { request } from "./api/client";

type Health = { mode: string; worker?: { status: string } };

export function ReleaseWorkerStatus() {
  const [status, setStatus] = useState("CHECKING");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  async function refresh() {
    if (controller.current) return;
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    try {
      const health = await request<Health>("/api/health", { signal: current.signal });
      if (!current.signal.aborted) setStatus(health.mode === "release_1_0_first_slice" ? health.worker?.status || "UNKNOWN" : "WRONG_SERVICE");
    } catch {
      if (!current.signal.aborted) setStatus("UNKNOWN");
    } finally {
      if (controller.current === current) controller.current = null;
      if (!current.signal.aborted) setBusy(false);
    }
  }
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { window.clearInterval(timer); controller.current?.abort(); controller.current = null; };
  }, []);
  if (status === "RUNNING") return <div role="status" className="release-worker-status"><Tag color="success">后台执行服务在线</Tag></div>;
  const notices: Record<string, string> = {
    CHECKING: "正在核对后台执行服务",
    NOT_RUNNING: "后台执行服务未启动：新任务仍在排队，定时采样不会触发。已有结果可继续查看，请管理员启动执行服务。",
    HEARTBEAT_STALE: "后台执行服务心跳超时：暂不能确认任务能继续执行，请管理员检查。不要重复提交相同任务。",
    HEARTBEAT_UNAVAILABLE: "后台执行服务心跳无法读取：运行状态待核实，不代表任务已完成。",
    WRONG_SERVICE: "当前 API 不是正式发布服务，请管理员检查启动入口。",
    UNKNOWN: "暂时无法读取后台运行状态，请稍后刷新；不能据此判断任务已停止或完成。",
  };
  return <Alert className="release-worker-status" showIcon type={status === "CHECKING" ? "info" : "warning"}
    message={<Space align="start"><span role="status">{notices[status] || notices.UNKNOWN}</span>
      <Tooltip title="核对后台执行服务"><Button aria-label="核对后台执行服务" loading={busy} icon={<RefreshCw size={14} />} onClick={() => void refresh()} /></Tooltip>
    </Space>} />;
}
