"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ArrowUp, FlaskConical, GitBranch, Search, ShieldCheck, UserRoundCheck } from "lucide-react";
import { $api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

export default function SimulatorPage() {
  const router = useRouter();
  const { data: templates, isLoading } = $api.useQuery("get", "/simulator/templates");
  const create = $api.useMutation("post", "/simulator/tickets");
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [tenant, setTenant] = useState("figma-merch");
  async function submit() {
    try {
      const result = await create.mutateAsync({ body: templateId ? { template_id: templateId, tenant_id: tenant, requester: null } : { subject, body, tenant_id: tenant, requester: null } });
      if (typeof result.ticket_id === "string") router.push(`/ticket/${encodeURIComponent(result.ticket_id)}`);
    } catch { toast.error("Could not create ticket. Check the API connection and try again."); }
  }
  return <div className="flex min-h-screen min-w-0">
    <main className="min-w-0 flex-1 px-6 py-8 xl:px-10"><div className="mx-auto max-w-3xl">
      <div className="mb-7 flex items-start gap-3"><div className="rounded-md border p-2"><FlaskConical size={20} /></div><div><h1 className="text-2xl font-semibold tracking-tight">Simulator</h1><p className="mt-1 text-sm text-muted-foreground">Test how Support Triage handles customer issues end to end.</p></div></div>
      <div className="space-y-3"><Input aria-label="Subject" placeholder="Subject" value={subject} onChange={(e) => { setSubject(e.target.value); setTemplateId(null); }} /><Textarea aria-label="Customer issue" className="min-h-44 resize-y text-sm" placeholder="Paste a customer issue or choose a scenario..." value={body} onChange={(e) => { setBody(e.target.value); setTemplateId(null); }} /><div className="flex items-center gap-3"><Input aria-label="Tenant ID" className="max-w-52" value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="Tenant ID" /><Button onClick={submit} disabled={create.isPending || !tenant.trim() || (!templateId && (!subject.trim() || !body.trim()))}>{create.isPending ? "Sending…" : "Run investigation"}<ArrowUp size={15} /></Button></div></div>
      <div className="mt-9"><h2 className="text-base font-semibold">Try a scenario</h2><p className="mt-1 text-sm text-muted-foreground">Choose a customer issue from the repository templates.</p><div className="mt-4 grid gap-3 md:grid-cols-2">{isLoading ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28" />) : templates?.map((template) => <Button key={template.id} variant="ghost" className="block h-auto w-full p-0 text-left whitespace-normal hover:bg-transparent" onClick={() => { setTemplateId(template.id); setSubject(template.subject); setBody(template.body); }}><Card className={`gap-2 py-4 shadow-none transition-colors hover:bg-muted/40 ${templateId === template.id ? "border-blue-400 bg-blue-50/50 dark:bg-blue-950/20" : ""}`}><CardHeader className="px-4"><CardTitle className="text-sm">{template.title}</CardTitle></CardHeader><CardContent className="px-4"><p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{template.body}</p>{templateId === template.id && <Badge variant="secondary" className="mt-3">Selected</Badge>}</CardContent></Card></Button>)}</div></div>
    </div></main>
    <aside className="hidden w-[310px] shrink-0 border-l p-6 xl:block"><h2 className="font-semibold">What this tests</h2><p className="mt-2 text-sm leading-relaxed text-muted-foreground">The simulator sends a ticket through the real intake and worker pipeline.</p><div className="mt-8 space-y-7 text-sm">{[[GitBranch, "Routing", "Classifies the issue and chooses a lane."], [Search, "Retrieval", "Finds relevant help and ticket context."], [UserRoundCheck, "Analyst handoff", "Investigates technical issues with evidence."], [ShieldCheck, "Approval flow", "Pauses when a person needs to review the reply."]].map(([Icon, label, description]) => { const IconComponent = Icon as typeof GitBranch; return <div key={label as string} className="flex gap-3"><IconComponent size={17} className="mt-0.5 shrink-0 text-muted-foreground" /><div><p className="font-medium">{label as string}</p><p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description as string}</p></div></div>; })}</div></aside>
  </div>;
}
