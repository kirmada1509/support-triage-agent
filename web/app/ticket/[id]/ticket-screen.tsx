"use client";

import { useMemo, useRef, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { format, formatDistanceToNow, differenceInSeconds } from "date-fns";
import { ReactFlow, Background, type Edge } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import JsonView from "@uiw/react-json-view";
import { toast } from "sonner";
import { ArrowLeft, ExternalLink, LoaderCircle, Pause, Play, Radio, RotateCcw, SkipForward } from "lucide-react";
import { $api } from "@/lib/api";
import { useTicketEvents } from "@/lib/use-ticket-events";
import type { components } from "@/lib/schema";
import { StageNode, type StageFlowNode } from "@/components/stage-node";
import { OutputView } from "@/components/output-view";
import { Tool, ToolContent, ToolHeader, ToolInput } from "@/components/ai-elements/tool";
import { CodeBlock, CodeBlockCopyButton, CodeBlockHeader, CodeBlockTitle } from "@/components/ai-elements/code-block";
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";
import { Sources, SourcesContent, SourcesTrigger } from "@/components/ai-elements/sources";
import { Confirmation, ConfirmationActions, ConfirmationAction, ConfirmationRequest, ConfirmationTitle } from "@/components/ai-elements/confirmation";
import { StackTrace } from "@/components/ai-elements/stack-trace";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import paymentDemo from "@/fixtures/payment-investigation.json";

type StoredEvent = components["schemas"]["StoredEvent"];
type Detail = components["schemas"]["TicketDetail"];
type Outcome = components["schemas"]["OutcomeEvent"];

const nodeTypes = { stage: StageNode };
function title(value: string | null | undefined) { return value?.replaceAll("_", " ") ?? "—"; }

function EnrichmentSummary({ data }: { data: Record<string, unknown> }) {
  const string = (key: string) => typeof data[key] === "string" ? data[key] as string : null;
  const list = (key: string) => Array.isArray(data[key]) ? (data[key] as unknown[]).filter((value): value is string => typeof value === "string") : [];
  const changes = Array.isArray(data.relevant_changes) ? data.relevant_changes.map((change) => typeof change === "string" ? change : change && typeof change === "object" ? Object.entries(change).map(([key, value]) => `${title(key)}: ${String(value)}`).join(", ") : "").filter(Boolean) : [];
  const identifiers = data.identifiers && typeof data.identifiers === "object" && !Array.isArray(data.identifiers) ? Object.entries(data.identifiers) : [];
  const rows = [
    ["Symptom", string("symptom")],
    ["Window", [string("window_start"), string("window_end")].filter(Boolean).join(" → ")],
    ["Window basis", string("window_basis")],
    ["Likely services", list("likely_services").join(", ")],
    ["Identifiers", identifiers.map(([key, value]) => `${title(key)}: ${Array.isArray(value) ? value.join(", ") : String(value)}`).join(" · ")],
    ["Relevant changes", changes.join(" · ")],
    ["Missing information", list("missing").join(" · ")],
  ].filter((row) => row[1]);
  return <dl className="mt-2 divide-y rounded-md border text-sm">{rows.map(([label, value]) => <div key={label} className="grid gap-2 px-3 py-2.5 sm:grid-cols-[120px_1fr]"><dt className="text-xs font-medium text-muted-foreground">{label}</dt><dd className="leading-relaxed">{value}</dd></div>)}</dl>;
}

function OutcomeSection({ outcome }: { outcome: Outcome }) {
  return <Card className="mt-5 gap-3 border-green-200 bg-green-50/30 shadow-none dark:border-green-900 dark:bg-green-950/20">
    <CardHeader><CardTitle className="flex items-center gap-2 text-base">Outcome <Badge variant="secondary" className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">{title(outcome.verdict_kind ?? outcome.lane)}</Badge></CardTitle></CardHeader>
    <CardContent className="space-y-4 text-sm"><p className="leading-relaxed">{outcome.summary}</p>
      {outcome.root_cause && <div><p className="mb-1 text-xs font-medium text-muted-foreground">Root cause</p><p>{outcome.root_cause}</p></div>}
      {(outcome.file_line || outcome.commit) && <div><p className="mb-1 text-xs font-medium text-muted-foreground">Code</p><p className="font-mono text-xs">{outcome.file_line}{outcome.commit && ` · ${outcome.commit.slice(0, 10)}`}</p></div>}
      {outcome.duplicate_of && <p>Linked to ticket {outcome.duplicate_of}</p>}
      <Separator />
      <div className="grid gap-2 text-xs text-muted-foreground"><p>Engineering handoff: {outcome.linear_issue ?? (outcome.engineering_handoff === "local_only" ? "Recorded locally" : "Not needed")}</p><p>Customer reply: {outcome.reply_delivery === "sent" ? "Delivered" : outcome.reply_delivery === "logged" ? "Logged locally" : "Not sent"}{outcome.approved === true ? " · Approved" : ""}</p></div>
      {outcome.reply && <div className="rounded-md bg-background p-3 text-sm whitespace-pre-wrap">{outcome.reply}</div>}
    </CardContent>
  </Card>;
}

function ApprovalSection({ id, draft, reasons, replay, pending, demoApprove }: { id: string; draft: string; reasons: string[]; replay: boolean; pending: boolean; demoApprove?: (reply: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [reply, setReply] = useState(draft);
  const approve = $api.useMutation("post", "/tickets/{ticket_id}/approve");
  async function submit(edited: boolean) {
    if (demoApprove) { demoApprove(edited ? reply : draft); setEditing(false); return; }
    try {
      const result = await approve.mutateAsync({ params: { path: { ticket_id: id } }, body: { approved: true, edited_reply: edited ? reply : null } });
      if (result?.ok) { setEditing(false); toast.success("Reply approved. The investigation is resuming."); }
    } catch { toast.error("Approval failed. Please try again."); }
  }
  return <>
    <Confirmation approval={{ id }} state="approval-requested" className="mt-4 border-amber-200 bg-amber-50/40 dark:border-amber-900 dark:bg-amber-950/20">
      <ConfirmationTitle>Approval required</ConfirmationTitle>
      <ConfirmationRequest><p className="text-sm text-muted-foreground">{reasons.join(" · ")}</p><p className="mt-2 whitespace-pre-wrap text-sm">{draft || "No draft reply was prepared. Write one before approving."}</p></ConfirmationRequest>
      {!replay && pending && <ConfirmationActions><ConfirmationAction onClick={() => submit(false)} disabled={approve.isPending || !draft.trim()}>{demoApprove ? "Simulate approval" : "Approve reply"}</ConfirmationAction><Button variant="outline" size="sm" onClick={() => { setReply(draft); setEditing(true); }} disabled={approve.isPending}>Edit</Button></ConfirmationActions>}
    </Confirmation>
    <Dialog open={editing} onOpenChange={setEditing}><DialogContent><DialogHeader><DialogTitle>Edit customer reply</DialogTitle><DialogDescription>{demoApprove ? "This changes only the simulated outcome." : "Review the reply before resuming this ticket."}</DialogDescription></DialogHeader><Textarea value={reply} onChange={(e) => setReply(e.target.value)} rows={10} /><DialogFooter><Button variant="outline" onClick={() => setEditing(false)}>Cancel</Button><Button onClick={() => submit(true)} disabled={approve.isPending || !reply.trim()}>{demoApprove ? "Simulate edited approval" : "Approve edited reply"}</Button></DialogFooter></DialogContent></Dialog>
  </>;
}

function TimelineEntry({ item, ticketId, replay, pending, nested = false, demoApprove }: { item: StoredEvent; ticketId: string; replay: boolean; pending: boolean; nested?: boolean; demoApprove?: (reply: string) => void }) {
  const event = item.event;
  if (event.kind === "stage" && event.status === "skipped") return null;
  const actor = event.stage ? title(event.stage) : "System";
  return <div className={`relative ${nested ? "border-l border-border/70 py-2 pl-4" : "pl-8 pb-7 before:absolute before:top-0 before:left-[7px] before:h-full before:w-px before:bg-border last:before:hidden"}`}>
    {!nested && <span className={`absolute top-1 left-0 size-[15px] rounded-full border-[3px] border-background ${event.kind === "error" || (event.kind === "stage" && event.status === "failed") ? "bg-red-500" : event.kind === "stage" && event.status === "done" ? "bg-green-500" : "bg-blue-500"}`} />}
    <div className="mb-1 flex items-center gap-2">{!nested && <span className="text-xs font-semibold capitalize">{actor}</span>}{event.kind === "stage" && event.status === "running" && <LoaderCircle size={13} className="animate-spin text-blue-600" />}<time className="text-[11px] text-muted-foreground">{format(item.ts, "h:mm a")}</time></div>
    {event.kind === "stage" && <p className="text-sm text-muted-foreground">{event.summary ?? (event.status === "running" ? "Working…" : title(event.status))}</p>}
    {event.kind === "tool_call" && <Tool defaultOpen={event.status === "error"} className="mt-2 mb-0 shadow-none"><ToolHeader type="dynamic-tool" toolName={event.tool} state={event.status === "running" ? "input-available" : event.status === "error" ? "output-error" : "output-available"} title={`${event.tool}${event.duration_ms != null ? ` · ${event.duration_ms} ms` : ""}`} /><ToolContent>{typeof event.args.command === "string" ? <CodeBlock code={event.args.command} language="bash"><CodeBlockHeader><CodeBlockTitle>Command</CodeBlockTitle><CodeBlockCopyButton /></CodeBlockHeader></CodeBlock> : Object.keys(event.args).length > 0 && <ToolInput input={event.args} />}{event.output ? <OutputView output={event.output} /> : event.status === "running" && <Shimmer className="text-xs">Tool details will appear when available.</Shimmer>}</ToolContent></Tool>}
    {event.kind === "model_delta" && <Message from="assistant"><MessageContent><MessageResponse>{event.text}</MessageResponse></MessageContent></Message>}
    {event.kind === "model_output" && <div className="mt-2"><p className="mb-2 text-sm font-medium">{event.name}</p>{event.stage === "enrich" ? <EnrichmentSummary data={event.data} /> : <JsonView value={event.data} collapsed={1} />}</div>}
    {event.kind === "retrieval" && <div className="mt-2"><p className="mb-2 text-sm text-muted-foreground">Search: {event.query}</p><Sources><SourcesTrigger count={event.results.length} /><SourcesContent>{event.results.map((result) => <div key={`${result.kind}-${result.id}`} className="text-xs"><Badge variant="outline" className="mr-2">{title(result.kind)}</Badge><span className="font-medium">{result.title}</span><span className="ml-2 text-muted-foreground">{result.score.toFixed(2)}</span></div>)}</SourcesContent></Sources></div>}
    {event.kind === "jev" && <div className="mt-2 flex flex-wrap gap-2">{event.answers.map((answer) => <Badge variant="secondary" key={answer.question} className="font-normal">{title(answer.question)}: {String(answer.answer)} · {Math.round(answer.confidence * 100)}%</Badge>)}</div>}
    {event.kind === "approval_required" && <ApprovalSection id={ticketId} draft={event.draft_reply} reasons={event.reasons} replay={replay} pending={pending} demoApprove={demoApprove} />}
    {event.kind === "link" && <Button asChild variant="link" className="h-auto p-0 text-sm"><a href={event.url} target="_blank" rel="noreferrer">{event.label} <ExternalLink size={12} /></a></Button>}
    {event.kind === "delivery" && <p className="text-sm text-muted-foreground">{event.detail}</p>}
    {event.kind === "outcome" && <OutcomeSection outcome={event} />}
    {event.kind === "error" && <Alert variant="destructive" className="mt-2"><AlertDescription>{event.message}</AlertDescription>{event.traceback && <StackTrace trace={event.traceback} className="mt-2" />}</Alert>}
  </div>;
}

function AnalystGroup({ stage, items, status, ticketId, replay, pending, focused }: { stage: string; items: StoredEvent[]; status: string; ticketId: string; replay: boolean; pending: boolean; focused: boolean }) {
  const [open, setOpen] = useState(status === "running" || focused);
  const summary = [...items].reverse().find((item) => item.event.kind === "stage" && item.event.summary)?.event;
  return <Collapsible open={open} onOpenChange={setOpen} className="relative mb-5 pl-8 before:absolute before:top-0 before:left-[7px] before:h-full before:w-px before:bg-border">
    <span className={`absolute top-1 left-0 size-[15px] rounded-full border-[3px] border-background ${status === "done" ? "bg-green-500" : status === "failed" ? "bg-red-500" : "bg-blue-500"}`} />
    <CollapsibleTrigger asChild><Button variant="ghost" className="-ml-2 h-auto w-full justify-start gap-2 px-2 py-1 text-left"><span className="text-xs font-semibold capitalize">{title(stage)}</span>{status === "running" && <LoaderCircle size={13} className="animate-spin text-blue-600" />}<Badge variant="outline" className="text-[10px] capitalize">{status}</Badge><span className="ml-auto text-[11px] text-muted-foreground">{items.length} updates · {format(items[0].ts, "h:mm a")}</span></Button></CollapsibleTrigger>
    {summary?.kind === "stage" && summary.summary && <p className="mt-1 text-sm text-muted-foreground">{summary.summary}</p>}
    <CollapsibleContent className="mt-3 space-y-1">{items.filter((item) => item.event.kind !== "stage").map((item) => <TimelineEntry key={item.id} item={item} ticketId={ticketId} replay={replay} pending={pending} nested />)}</CollapsibleContent>
  </Collapsible>;
}

function Details({ ticket, outcome, demo = false }: { ticket: Detail; outcome: Outcome | null; demo?: boolean }) {
  const duration = differenceInSeconds(ticket.completed_at ?? new Date(), ticket.received_at);
  return <div className="space-y-5 p-5 text-sm">
    <h2 className="font-semibold">Ticket details</h2>
    <dl className="grid grid-cols-[85px_1fr] gap-y-2.5"><dt className="text-muted-foreground">ID</dt><dd>#{ticket.id}</dd><dt className="text-muted-foreground">Status</dt><dd className="capitalize">{title(ticket.status)}</dd><dt className="text-muted-foreground">Severity</dt><dd>{ticket.severity ? `Sev ${ticket.severity}` : "—"}</dd><dt className="text-muted-foreground">Lane</dt><dd className="capitalize">{title(ticket.lane)}</dd><dt className="text-muted-foreground">Tenant</dt><dd>{ticket.tenant_id ?? "—"}</dd><dt className="text-muted-foreground">Created</dt><dd>{demo ? format(ticket.received_at, "MMM d, yyyy") : formatDistanceToNow(ticket.received_at, { addSuffix: true })}</dd><dt className="text-muted-foreground">Duration</dt><dd>{demo && !outcome ? "—" : `${Math.max(0, Math.floor(duration / 60))}m ${Math.max(0, duration % 60)}s`}</dd><dt className="text-muted-foreground">Cost</dt><dd>{demo && !outcome ? "—" : `$${ticket.cost_usd.toFixed(3)}`}</dd></dl>
    <Separator />
    <section><h3 className="mb-2 font-medium">Customer</h3><p className="text-muted-foreground">{ticket.requester ?? ticket.tenant_id ?? "Unknown"}</p></section>
    <Separator />
    <section><h3 className="mb-2 font-medium">Customer message</h3><p className="rounded-md bg-muted/60 p-3 leading-relaxed whitespace-pre-wrap">{ticket.body}</p></section>
    {ticket.jev && <><Separator /><section><h3 className="mb-3 font-medium">Classification</h3><div className="space-y-3">{ticket.jev.answers.map((answer) => <div key={answer.question}><div className="mb-1 flex justify-between text-xs"><span className="capitalize text-muted-foreground">{title(answer.question)}</span><span>{String(answer.answer)}</span></div><Progress value={answer.confidence * 100} className="h-1" /></div>)}</div></section></>}
    {ticket.links.length > 0 && <><Separator /><section><h3 className="mb-2 font-medium">Evidence & links</h3><div className="space-y-2">{ticket.links.map((link) => <a key={link.url} href={link.url} target="_blank" rel="noreferrer" className="flex items-center justify-between text-sm text-blue-700 hover:underline dark:text-blue-300">{link.label}<ExternalLink size={13} /></a>)}</div></section></>}
    {outcome && <><Separator /><section><h3 className="mb-2 font-medium">Final result</h3><p className="leading-relaxed">{outcome.summary}</p><p className="mt-2 text-xs text-muted-foreground">{outcome.reply_delivery === "sent" ? "Reply delivered" : outcome.reply_delivery === "logged" ? "Reply logged locally" : "No reply sent"}</p></section></>}
  </div>;
}

export default function TicketScreen() {
  const { id } = useParams<{ id: string }>();
  const demo = id === "demo";
  const searchParams = useSearchParams();
  const replay = !demo && searchParams.get("replay") === "1";
  const [selectedStage, setSelectedStage] = useState("all");
  const [followLive, setFollowLive] = useState(true);
  const [view, setView] = useState("live");
  const [demoIndex, setDemoIndex] = useState(0);
  const [demoPlaying, setDemoPlaying] = useState(false);
  const [demoNeedsApproval, setDemoNeedsApproval] = useState(false);
  const [demoReply, setDemoReply] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const { data: liveTicket, isLoading, error } = $api.useQuery("get", "/tickets/{ticket_id}", { params: { path: { ticket_id: id } } }, { enabled: !demo, refetchInterval: replay || demo ? false : 2000 });
  const { data: livePipeline } = $api.useQuery("get", "/pipeline", {}, { enabled: !demo });
  const demoEvents = useMemo(() => demo ? paymentDemo.events.slice(0, demoIndex) as unknown as StoredEvent[] : undefined, [demo, demoIndex]);
  const { events, stageStatuses, activeStage, isConnected } = useTicketEvents(id, replay, demoEvents);
  useEffect(() => {
    if (!demo || !demoPlaying || demoNeedsApproval || demoIndex >= paymentDemo.events.length) return;
    const next = paymentDemo.events[demoIndex] as StoredEvent;
    const delay = next.event.kind === "stage" && next.event.status === "running" ? 700 : 190;
    const timer = window.setTimeout(() => {
      setDemoIndex((index) => index + 1);
      if (next.event.kind === "approval_required") { setDemoPlaying(false); setDemoNeedsApproval(true); }
      if (demoIndex + 1 >= paymentDemo.events.length) setDemoPlaying(false);
    }, delay);
    return () => window.clearTimeout(timer);
  }, [demo, demoPlaying, demoNeedsApproval, demoIndex]);
  const ticket = demo ? { ...paymentDemo.ticket, status: (demoNeedsApproval ? "needs_approval" : events.some((item) => item.event.kind === "outcome") ? "done" : demoIndex === 0 ? "queued" : "running") as Detail["status"], jev: events.findLast((item) => item.event.kind === "jev")?.event ?? null } as Detail : liveTicket;
  const pipeline = demo ? paymentDemo.pipeline as unknown as components["schemas"]["Pipeline"] : livePipeline;
  const outcome = events.findLast((item) => item.event.kind === "outcome")?.event;
  const visibleOutcome = outcome?.kind === "outcome" ? demoReply ? { ...outcome, reply: demoReply } : outcome : replay || demo ? null : ticket?.outcome ?? null;
  const displayed = useMemo(() => {
    const latestCall = new Map<string, number>();
    for (const item of events) if (item.event.kind === "tool_call") latestCall.set(`${item.event.stage}:${item.event.call_id}`, item.id);
    const compact: StoredEvent[] = [];
    for (const item of events) {
      if (item.event.kind === "tool_call" && latestCall.get(`${item.event.stage}:${item.event.call_id}`) !== item.id) continue;
      if (item.event.kind === "stage" && item.event.status === "running" && stageStatuses[item.event.stage]?.status !== "running") continue;
      const previous = compact.at(-1);
      if (item.event.kind === "model_delta" && previous?.event.kind === "model_delta" && previous.event.stage === item.event.stage) {
        compact[compact.length - 1] = { ...previous, event: { ...previous.event, text: previous.event.text + item.event.text } };
      } else compact.push(item);
    }
    return selectedStage === "all" ? compact : compact.filter((item) => item.event.stage === selectedStage);
  }, [events, selectedStage, stageStatuses]);
  const timeline = useMemo(() => {
    const blocks: ({ kind: "single"; item: StoredEvent } | { kind: "analyst"; stage: string; items: StoredEvent[] })[] = [];
    const groups = new Map<string, StoredEvent[]>();
    for (const item of displayed) {
      const stage = item.event.stage;
      if (stage && ["data_analyst", "codebase_analyst", "round2"].includes(stage)) {
        let group = groups.get(stage);
        if (!group) { group = []; groups.set(stage, group); blocks.push({ kind: "analyst", stage, items: group }); }
        group.push(item);
      } else blocks.push({ kind: "single", item });
    }
    return blocks;
  }, [displayed]);
  useEffect(() => { if (followLive) end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [displayed.length, activeStage, followLive]);
  const flowNodes = useMemo<StageFlowNode[]>(() => (pipeline?.nodes ?? []).filter((node) => !node.id.startsWith("__")).map((node) => ({
    id: node.id, type: "stage", position: { x: node.position.y * 1.2 - 60, y: 80 + node.position.x * 0.18 },
    data: { label: node.label, status: stageStatuses[node.id]?.status ?? "waiting" }, selected: selectedStage === node.id,
  })), [pipeline, stageStatuses, selectedStage]);
  const flowEdges = useMemo<Edge[]>(() => (pipeline?.edges ?? []).filter((edge) => !edge.source.startsWith("__") && !edge.target.startsWith("__")).map((edge) => ({
    id: edge.id, source: edge.source, target: edge.target, type: "smoothstep", animated: stageStatuses[edge.target]?.status === "running",
    style: { stroke: stageStatuses[edge.target]?.status === "done" ? "#22c55e" : stageStatuses[edge.target]?.status === "running" ? "#3b82f6" : "#d4d4d8", strokeWidth: 1.5, opacity: stageStatuses[edge.source]?.status === "skipped" || stageStatuses[edge.target]?.status === "skipped" ? 0.25 : 1 },
  })), [pipeline, stageStatuses]);
  if (!demo && isLoading) return <div className="space-y-5 p-8"><Skeleton className="h-8 w-2/3" /><Skeleton className="h-36 w-full" /><Skeleton className="h-96 w-full" /></div>;
  if (error || !ticket) return <div className="p-10"><h1 className="text-xl font-semibold">Ticket not found</h1><Button asChild variant="link" className="mt-3 p-0"><Link href="/tickets">Back to tickets</Link></Button></div>;
  return <div className="flex min-h-screen min-w-0">
    <main className="min-w-0 flex-1 px-5 py-5 lg:px-8">
      <header className="mb-5"><div className="mb-4 flex items-center justify-between"><Button asChild variant="ghost" size="sm" className="-ml-2 text-muted-foreground"><Link href="/tickets"><ArrowLeft size={15} /> Tickets</Link></Button><div className="flex items-center gap-2">{demo && <Badge variant="secondary">Simulated demo · offline</Badge>}{replay && <Badge variant="secondary">Replay</Badge>}{!replay && !demo && <Button asChild variant="outline" size="sm"><Link href={`/ticket/${encodeURIComponent(id)}?replay=1`}><RotateCcw size={13} /> Replay</Link></Button>}<Sheet><SheetTrigger asChild><Button variant="outline" size="sm" className="xl:hidden">Details</Button></SheetTrigger><SheetContent className="overflow-y-auto"><SheetHeader><SheetTitle>Ticket details</SheetTitle></SheetHeader><Details ticket={ticket} outcome={visibleOutcome} demo={demo} /></SheetContent></Sheet></div></div><h1 className="text-xl font-semibold tracking-tight"><span className="mr-2 text-muted-foreground">#{ticket.id}</span>{ticket.subject}</h1><p className="mt-1 text-xs text-muted-foreground">{ticket.tenant_id ?? "Unknown tenant"} · {title(ticket.lane)} · {ticket.severity ? `Sev ${ticket.severity}` : "Severity pending"} · {demo ? `Recorded ${format(ticket.received_at, "MMM d, yyyy")}` : `Created ${formatDistanceToNow(ticket.received_at, { addSuffix: true })}`}</p></header>
      {demo && <div className="mb-5 flex items-center gap-2 border-b pb-4"><Button size="sm" variant="outline" onClick={() => setDemoPlaying((playing) => !playing)} disabled={demoNeedsApproval || demoIndex >= paymentDemo.events.length}>{demoPlaying ? <Pause size={14} /> : <Play size={14} />}{demoPlaying ? "Pause" : "Play"}</Button><Button size="sm" variant="outline" onClick={() => { const next = paymentDemo.events[demoIndex] as StoredEvent | undefined; if (!next || demoNeedsApproval) return; setDemoPlaying(false); setDemoIndex(demoIndex + 1); if (next.event.kind === "approval_required") setDemoNeedsApproval(true); }} disabled={demoNeedsApproval || demoIndex >= paymentDemo.events.length}><SkipForward size={14} /> Step</Button><Button size="sm" variant="ghost" onClick={() => { setDemoPlaying(false); setDemoIndex(0); setDemoNeedsApproval(false); setDemoReply(null); setSelectedStage("all"); }}><RotateCcw size={14} /> Restart</Button><span className="ml-auto text-xs text-muted-foreground">{demoNeedsApproval ? "Paused for simulated approval" : `${demoIndex} / ${paymentDemo.events.length} recorded events`}</span></div>}
      <section aria-label="Pipeline" className="mb-6 rounded-md border"><div className="flex items-center justify-between border-b px-4 py-2"><h2 className="text-xs font-semibold">Pipeline</h2><div className="flex items-center gap-2"><Button variant="ghost" size="xs" onClick={() => { setSelectedStage("all"); setFollowLive(false); }}>All activity</Button><Button variant={followLive ? "secondary" : "ghost"} size="xs" onClick={() => { setSelectedStage("all"); setFollowLive(true); }}><Radio size={12} /> Follow live</Button></div></div>{pipeline ? <div className="overflow-x-auto"><div className="h-[180px] w-[1900px]"><ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} onNodeClick={(_, node) => { setSelectedStage(node.id); setFollowLive(false); }} fitView={false} defaultViewport={{ x: 0, y: 0, zoom: 1 }} nodesDraggable={false} nodesConnectable={false} panOnDrag={false} zoomOnScroll={false} zoomOnPinch={false} zoomOnDoubleClick={false}><Background gap={24} size={0.5} color="var(--border)" /></ReactFlow></div></div> : <p className="p-5 text-xs text-muted-foreground">Pipeline unavailable. Investigation activity is still shown below.</p>}</section>
      <div className="mb-5 flex items-center justify-between"><div><h2 className="text-sm font-semibold">Investigation</h2><p className="text-xs text-muted-foreground">{selectedStage === "all" ? "All activity" : title(selectedStage)} · {demo ? "Simulated playback" : replay ? "Replay" : isConnected ? "Live" : "Reconnecting…"}</p></div><Tabs value={view} onValueChange={setView} className="w-auto"><TabsList variant="line"><TabsTrigger value="live">Live</TabsTrigger><TabsTrigger value="raw">Raw</TabsTrigger></TabsList></Tabs></div>
      {view === "live" ? <div className="max-w-3xl">{timeline.length ? timeline.map((block) => block.kind === "analyst" ? <AnalystGroup key={`${block.stage}-${stageStatuses[block.stage]?.status}-${selectedStage}`} stage={block.stage} items={block.items} status={stageStatuses[block.stage]?.status ?? "waiting"} ticketId={id} replay={replay} pending={ticket.status === "needs_approval"} focused={selectedStage === block.stage} /> : <TimelineEntry key={block.item.id} item={block.item.event.kind === "outcome" && visibleOutcome ? { ...block.item, event: visibleOutcome } : block.item} ticketId={id} replay={replay} pending={ticket.status === "needs_approval"} demoApprove={demo ? (reply) => { setDemoReply(reply); setDemoNeedsApproval(false); setDemoPlaying(true); } : undefined} />) : <div className="py-14 text-center text-sm text-muted-foreground"><Shimmer>Waiting for the investigation to start…</Shimmer></div>}{visibleOutcome && !events.some((item) => item.event.kind === "outcome") && <OutcomeSection outcome={visibleOutcome} />}</div> : <div className="max-w-3xl"><JsonView value={selectedStage === "all" ? events : events.filter((item) => item.event.stage === selectedStage)} collapsed={2} /></div>}<div ref={end} />
    </main>
    <aside className="hidden w-[310px] shrink-0 border-l xl:block"><div className="sticky top-0 max-h-screen overflow-y-auto"><Details ticket={ticket} outcome={visibleOutcome} demo={demo} /></div></aside>
  </div>;
}
