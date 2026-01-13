import { NextResponse } from "next/server";
import { jobConfigSchema } from "@/lib/configSchema";
import { supabaseServiceRole } from "@/lib/supabaseServer";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const rawConfig = body?.config;
    const parsed = jobConfigSchema.safeParse(rawConfig);
    if (!parsed.success) {
      return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
    }
    const config = parsed.data;
    const userId = body?.user_id || body?.userId || process.env.DEFAULT_USER_ID || "00000000-0000-0000-0000-000000000000";
    const sb = supabaseServiceRole();
    if (!sb) {
      return NextResponse.json({ error: "Supabase is not configured." }, { status: 503 });
    }
    const { data, error } = await sb
      .from("jobs")
      .insert({
        user_id: userId,
        title: body?.title || "Lit review run",
        research_focus: body?.research_focus || config.research_focus,
        input_uri: body?.input_uri || config.pdf_dir,
        config,
        status: "queued"
      })
      .select("id")
      .single();
    if (error) {
      throw error;
    }
    await sb.from("job_events").insert({
      job_id: data.id,
      event_type: "status",
      message: "Job queued from UI",
      data: {}
    });
    return NextResponse.json({ id: data.id });
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || "Failed to enqueue job" }, { status: 500 });
  }
}
