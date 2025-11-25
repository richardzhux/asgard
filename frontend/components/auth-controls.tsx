"use client";

import { useSession, useSupabaseClient } from "@supabase/auth-helpers-react";
import { Button } from "@/components/ui/button";

export function AuthControls() {
  const session = useSession();
  const supabase = useSupabaseClient();

  const signIn = async () => {
    await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/` }
    });
  };

  const signOut = async () => {
    await supabase.auth.signOut();
  };

  if (!session) {
    return (
      <Button variant="ghost" onClick={signIn} size="sm">
        Sign in with Google
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <div className="text-sm text-foreground/70">Hi, {session.user.email}</div>
      <Button variant="ghost" size="sm" onClick={signOut}>
        Sign out
      </Button>
    </div>
  );
}
