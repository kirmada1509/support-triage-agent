"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ArrowRight, Check, FlaskConical, GitBranch, LoaderCircle, MessageSquareText, Search, ShieldCheck, UserRoundCheck } from "lucide-react";
import { $api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";

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
    <main className="min-w-0 flex-1 px-6 py-5 xl:px-8"><div className="mx-auto max-w-3xl">
      <div className="mb-7"><div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground"><FlaskConical size={13} /> Test a case</div><h1 className="text-xl font-semibold tracking-tight">Simulator</h1><p className="mt-1 text-xs text-muted-foreground">Test how Support Triage handles customer issues end to end.</p></div>
      <div className="space-y-4"><div><label htmlFor="sim-subject" className="mb-1.5 block text-xs font-medium">Subject</label><Input id="sim-subject" aria-label="Subject" placeholder="A short summary of the issue" value={subject} onChange={(e) => { setSubject(e.target.value); setTemplateId(null); }} /></div><div><label htmlFor="sim-message" className="mb-1.5 block text-xs font-medium">Customer message</label><Textarea id="sim-message" aria-label="Customer issue" className="min-h-44 resize-y text-sm" placeholder="Paste a customer issue or choose a scenario..." value={body} onChange={(e) => { setBody(e.target.value); setTemplateId(null); }} /></div><div className="flex flex-wrap items-end justify-between gap-3"><div><label htmlFor="sim-tenant" className="mb-1.5 block text-xs font-medium">Tenant ID</label><Input id="sim-tenant" aria-label="Tenant ID" className="w-52" value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="Tenant ID" /></div><Button onClick={submit} disabled={create.isPending || !tenant.trim() || (!templateId && (!subject.trim() || !body.trim()))}>{create.isPending ? <LoaderCircle size={15} className="animate-spin" /> : <ArrowRight size={15} />}{create.isPending ? "Starting investigation…" : "Run investigation"}</Button></div></div>
      <Separator className="my-8" />
      <div><h2 className="text-sm font-semibold">Try a scenario</h2><p className="mt-1 text-xs text-muted-foreground">Choose a sample customer issue to fill the form.</p><div className="mt-4 grid gap-3 md:grid-cols-2">{isLoading ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28" />) : templates?.map((template) => <Button key={template.id} variant="ghost" className="block h-auto w-full p-0 text-left whitespace-normal hover:bg-transparent" onClick={() => { setTemplateId(template.id); setSubject(template.subject); setBody(template.body); }}><Card className={`h-full gap-2 py-3 shadow-none transition-colors hover:bg-muted/40 ${templateId === template.id ? "border-blue-300 bg-blue-50/50 dark:border-blue-900 dark:bg-blue-950/20" : ""}`}><CardHeader className="px-4"><CardTitle className="flex items-center gap-2 text-sm"><span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground"><MessageSquareText size={14} /></span><span className="min-w-0 flex-1 truncate">{template.title}</span>{templateId === template.id && <Badge variant="outline" className="border-blue-200 bg-background text-[10px] text-blue-700 dark:border-blue-900 dark:text-blue-300"><Check size={11} /> Selected</Badge>}</CardTitle></CardHeader><CardContent className="px-4"><p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{template.body}</p></CardContent></Card></Button>)}</div></div>
    </div></main>
    <aside className="hidden w-[310px] shrink-0 border-l p-5 xl:block"><h2 className="text-sm font-semibold">What this tests</h2><p className="mt-2 text-xs leading-relaxed text-muted-foreground">The simulator sends a ticket through the real intake and worker pipeline.</p><Separator className="my-5" /><div className="space-y-6 text-sm">{[[GitBranch, "Routing", "Classifies the issue and chooses a lane."], [Search, "Retrieval", "Finds relevant help and ticket context."], [UserRoundCheck, "Analyst handoff", "Investigates technical issues with evidence."], [ShieldCheck, "Approval flow", "Pauses when a person needs to review the reply."]].map(([Icon, label, description]) => { const IconComponent = Icon as typeof GitBranch; return <div key={label as string} className="flex gap-3"><span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground"><IconComponent size={14} /></span><div><p className="text-xs font-medium">{label as string}</p><p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description as string}</p></div></div>; })}</div></aside>
  </div>;
}
