"use client";

import { useState, ReactNode } from "react";
import { Session, SessionContextProvider } from "@supabase/auth-helpers-react";
import { createBrowserSupabaseClient } from "@supabase/auth-helpers-nextjs";

export default function Providers({ children, initialSession }: { children: ReactNode; initialSession: Session | null }) {
  const [supabaseClient] = useState(() => createBrowserSupabaseClient());
  return <SessionContextProvider supabaseClient={supabaseClient} initialSession={initialSession}>{children}</SessionContextProvider>;
}
