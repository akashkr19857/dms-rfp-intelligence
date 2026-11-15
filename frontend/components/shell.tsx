"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, BookOpen, FileSearch, FlaskConical, Gavel, LogOut, MessageSquare, Moon, Sun } from "lucide-react";
import { AuthProvider, LoginScreen, useAuth } from "@/components/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Tenders", icon: Gavel },
  { href: "/ask", label: "Ask", icon: MessageSquare },
  { href: "/knowledge", label: "Knowledge base", icon: BookOpen },
  { href: "/evaluation", label: "Evaluation", icon: FlaskConical },
  { href: "/usage", label: "Usage & traces", icon: BarChart3 },
];

function ThemeToggle() {
  const [dark, setDark] = React.useState(false);
  React.useEffect(() => {
    let stored: string | null = null;
    try {
      stored = localStorage.getItem("rfp_theme");
    } catch {
      /* ignore */
    }
    const isDark = stored ? stored === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.classList.toggle("dark", isDark);
    setDark(isDark);
  }, []);
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("rfp_theme", next ? "dark" : "light");
    } catch {
      /* ignore */
    }
  };
  return (
    <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const path = usePathname();
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="flex shrink-0 flex-row items-center gap-1 border-b bg-card px-3 py-2 md:w-56 md:flex-col md:items-stretch md:border-b-0 md:border-r md:py-4">
        <Link href="/" className="mb-0 mr-3 flex items-center gap-2 px-2 text-lg font-bold md:mb-6 md:mr-0">
          <FileSearch className="h-6 w-6 text-primary" />
          <span className="leading-tight">DMS RFP<br /><span className="text-xs font-medium text-muted-foreground">Intelligence</span></span>
        </Link>
        <nav className="flex flex-1 flex-row gap-1 overflow-x-auto md:flex-col">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? path === "/" || path.startsWith("/tenders") : path.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm transition-colors",
                  active ? "bg-primary/12 font-medium text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
                <span className="hidden sm:inline">{label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="hidden px-2 text-[11px] leading-relaxed text-muted-foreground md:block">
          Local LLM · qwen2.5:7b via Ollama
          <br />
          RAG: BM25 + vectors + reranker
          <br />
          Every finding cites its page
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-end gap-2 border-b px-4">
          {user && (
            <div className="flex items-center gap-2 text-sm">
              <span className="hidden text-muted-foreground sm:inline" data-testid="current-user">{user.name}</span>
              {user.workspaces.map((w) => (
                <Badge key={w} variant="secondary" className="hidden lg:inline-flex">{w}</Badge>
              ))}
              <Button variant="ghost" size="sm" onClick={logout} aria-label="Switch user">
                <LogOut className="h-4 w-4" /> <span className="hidden sm:inline">Switch user</span>
              </Button>
            </div>
          )}
          <ThemeToggle />
        </header>
        <main className="min-w-0 flex-1 p-4 md:p-6">{loading ? null : user ? children : <LoginScreen />}</main>
      </div>
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <Frame>{children}</Frame>
    </AuthProvider>
  );
}
