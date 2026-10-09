import React from "react";
import ReactDOM from "react-dom/client";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import { AccessGate } from "./AccessGate";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#2764d8",
          colorPrimaryHover: "#245bbf",
          colorTextSecondary: "#595959",
          colorTextTertiary: "#666666",
          colorTextPlaceholder: "#6b6b6b",
          borderRadius: 6,
          fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
        }
      }}
    >
      <AntApp>
        {import.meta.env.VITE_GEO_RELEASE_FIRST_SLICE === "1" ? <AccessGate><App /></AccessGate> : <App />}
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>
);
