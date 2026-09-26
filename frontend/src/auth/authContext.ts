import { createContext, useContext } from "react";

export type AuthState =
  | { status: "loading"; token: null; name: null }
  | { status: "signed_out"; token: null; name: null }
  | { status: "signed_in"; token: string; name: string };

export interface AuthContextValue {
  state: AuthState;
  signOut: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("AuthProvider is missing");
  return context;
}
