import { useEffect, useRef, useState, type ReactNode } from "react";
import { Alert, Button, Card, Input, Space, Spin, Typography } from "antd";
import { UserManager, WebStorageStateStore, type User } from "oidc-client-ts";

import { AuthContext, type AuthState } from "./authContext";

const authority = import.meta.env.VITE_OIDC_AUTHORITY?.trim();
const clientId = import.meta.env.VITE_OIDC_CLIENT_ID?.trim();
const devTokenAllowed = import.meta.env.DEV && import.meta.env.VITE_DEV_TOKEN_AUTH === "true";

function createManager(): UserManager | null {
  if (!authority || !clientId) return null;
  return new UserManager({
    authority,
    client_id: clientId,
    redirect_uri: `${window.location.origin}/auth/callback`,
    post_logout_redirect_uri: window.location.origin,
    response_type: "code",
    scope: import.meta.env.VITE_OIDC_SCOPE || "openid profile",
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
    automaticSilentRenew: false,
  });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [manager] = useState(createManager);
  const [state, setState] = useState<AuthState>({ status: "loading", token: null, name: null });
  const [error, setError] = useState<string | null>(null);
  const [devToken, setDevToken] = useState("");
  const restorePromise = useRef<Promise<User | null> | null>(null);

  useEffect(() => {
    let active = true;
    const expired = () => setState({ status: "signed_out", token: null, name: null });
    manager?.events.addAccessTokenExpired(expired);
    async function restore() {
      if (!manager) {
        if (active) setState({ status: "signed_out", token: null, name: null });
        return;
      }
      try {
        // Keep one callback promise across StrictMode's development effect replay.
        restorePromise.current ??= window.location.pathname === "/auth/callback"
          ? manager.signinRedirectCallback()
          : manager.getUser();
        const user = await restorePromise.current;
        if (window.location.pathname === "/auth/callback") {
          window.history.replaceState({}, "", "/");
        }
        if (!active) return;
        if (user && !user.expired) {
          setState({
            status: "signed_in",
            token: user.access_token,
            name: user.profile.preferred_username || user.profile.name || user.profile.sub,
          });
        } else {
          setState({ status: "signed_out", token: null, name: null });
        }
      } catch {
        if (active) {
          setError("登录回调失败，请重试");
          setState({ status: "signed_out", token: null, name: null });
        }
      }
    }
    void restore();
    return () => {
      active = false;
      manager?.events.removeAccessTokenExpired(expired);
    };
  }, [manager]);

  async function signOut() {
    setState({ status: "signed_out", token: null, name: null });
    if (manager) await manager.signoutRedirect();
  }

  function signInWithDevToken() {
    const token = devToken.trim();
    if (!token) return;
    setState({ status: "signed_in", token, name: "本地演示" });
    setDevToken("");
  }

  const value = { state, signOut };
  return (
    <AuthContext.Provider value={value}>
      {state.status === "loading" ? (
        <div className="auth-loading"><Spin size="large" tip="正在连接身份服务" /></div>
      ) : state.status === "signed_in" ? children : (
        <div className="auth-page">
          <Card className="auth-card">
            <Space direction="vertical" size="large" style={{ width: "100%" }}>
              <div className="brand-mark">EA</div>
              <div>
                <Typography.Title level={2}>Enterprise Agent Console</Typography.Title>
                <Typography.Paragraph type="secondary">
                  管理知识库，检索证据，并核对 AI 回答的来源。
                </Typography.Paragraph>
              </div>
              {error && <Alert type="error" message={error} showIcon />}
              {manager ? (
                <Button type="primary" size="large" block onClick={() => void manager.signinRedirect()}>
                  使用企业身份登录
                </Button>
              ) : devTokenAllowed ? (
                <Space direction="vertical" style={{ width: "100%" }}>
                  <Alert type="info" showIcon message="本地演示入口：令牌仅保存在当前页面内存，刷新后需重新输入。" />
                  <Input.Password
                    aria-label="演示访问令牌"
                    placeholder="粘贴本机签发的演示 JWT"
                    value={devToken}
                    onChange={(event) => setDevToken(event.target.value)}
                    onPressEnter={signInWithDevToken}
                  />
                  <Button type="primary" block disabled={!devToken.trim()} onClick={signInWithDevToken}>
                    连接工作台
                  </Button>
                </Space>
              ) : (
                <Alert type="warning" showIcon message="尚未配置 OIDC 身份服务" description="请配置 VITE_OIDC_AUTHORITY 和 VITE_OIDC_CLIENT_ID。" />
              )}
            </Space>
          </Card>
        </div>
      )}
    </AuthContext.Provider>
  );
}
