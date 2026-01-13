import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { cookies } from "next/headers";
import { createServerComponentClient } from "@supabase/auth-helpers-nextjs";
import Providers from "@/components/providers";
import { TopNav } from "@/components/top-nav";

export const metadata: Metadata = {
  title: "Asgard Lit Review",
  description: "Control panel for the lit review pipeline."
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const supabaseReady = Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
  let session = null;
  if (supabaseReady) {
    const supabase = createServerComponentClient({ cookies });
    const {
      data: { session: s }
    } = await supabase.auth.getSession();
    session = s;
  }

  return (
    <html lang="en">
      <body>
        <Providers initialSession={session}>
          <div className="container">
            <TopNav />
            {children}
          </div>
        </Providers>
      </body>
    </html>
  );
}
