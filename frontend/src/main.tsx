import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { App, ConfigProvider, Spin } from "antd";
import zhCN from "antd/locale/zh_CN";
import { AuthProvider } from "./auth/AuthProvider";
import "./styles.css";

const Workspace = lazy(async () => {
  const module = await import("./Workspace");
  return { default: module.Workspace };
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#226a78", borderRadius: 10, fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" } }}>
      <App>
        <AuthProvider><Suspense fallback={<div className="auth-loading"><Spin size="large" /></div>}><Workspace /></Suspense></AuthProvider>
      </App>
    </ConfigProvider>
  </React.StrictMode>,
);
