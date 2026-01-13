"use client";

import { useState, ReactNode } from "react";
import { Session, SessionContextProvider } from "@supabase/auth-helpers-react";
import { createPagesBrowserClient } from "@supabase/auth-helpers-nextjs";

export default function Providers({ children, initialSession }: { children: ReactNode; initialSession: Session | null }) {
  const hasEnv = Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
  if (!hasEnv) {
    return <>{children}</>;
  }
  const [supabaseClient] = useState(() => createPagesBrowserClient());
  return <SessionContextProvider supabaseClient={supabaseClient} initialSession={initialSession}>{children}</SessionContextProvider>;
}
