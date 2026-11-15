"use client";

import * as React from "react";
import { FileSearch, Lock, ShieldCheck } from "lucide-react";
import { api, getToken, setToken, type User } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type AuthState = { user: User | null; loading: boolean; login: (id: string) => Promise<void>; logout: () => void };
const AuthContext = React.createContext<AuthState>({ user: null, loading: true, login: async () => {}, logout: () => {} });

export function useAuth() {
  return React.useContext(AuthContext);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<User | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api<User>("/api/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const login = React.useCallback(async (id: string) => {
    const res = await api<{ token: string; user: User }>("/api/login", { method: "POST", body: JSON.stringify({ user_id: id }) });
    setToken(res.token);
    setUser(res.user);
  }, []);
  const logout = React.useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function LoginScreen() {
  const { login } = useAuth();
  const [users, setUsers] = React.useState<User[]>([]);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    api<User[]>("/api/users").then(setUsers).catch((e) => setError(`API not reachable (${e.message}). Is the backend running on :8200?`));
  }, []);
  return (
    <div className="flex min-h-[80vh] items-center justify-center p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <div className="flex items-center gap-2 text-lg font-bold">
            <FileSearch className="h-6 w-6 text-primary" /> DMS RFP Intelligence
          </div>
          <CardTitle className="text-base">Choose a demo user</CardTitle>
          <CardDescription>
            Role-based access: each user only sees their own workspaces (the legal reviewer cannot see the knowledge base). Demo sign-in, no passwords; production would use SSO.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {error && <p className="text-sm text-destructive">{error}</p>}
          {users.map((u) => (
            <button
              key={u.id}
              data-testid={`login-${u.id}`}
              onClick={() => login(u.id).catch((e) => setError(e.message))}
              className="flex w-full items-center justify-between rounded-md border p-3 text-left transition hover:border-primary hover:bg-accent"
            >
              <div>
                <div className="flex items-center gap-2 font-medium">
                  {u.role === "admin" ? <ShieldCheck className="h-4 w-4 text-primary" /> : <Lock className="h-4 w-4 text-muted-foreground" />}
                  {u.name}
                </div>
                <div className="mt-1 flex gap-1">
                  {u.workspaces.map((w) => (
                    <Badge key={w} variant="secondary">{w}</Badge>
                  ))}
                </div>
              </div>
              <Badge variant={u.role === "admin" ? "default" : "outline"}>{u.role}</Badge>
            </button>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
