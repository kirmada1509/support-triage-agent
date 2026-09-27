"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { formatDistanceToNow, differenceInSeconds } from "date-fns";
import { useReactTable, getCoreRowModel, type ColumnDef } from "@tanstack/react-table";
import { toast } from "sonner";
import { ArrowRight, Check, ChevronLeft, ChevronRight, Clock3, Inbox, LoaderCircle, PanelRightClose, PanelRightOpen, Plus, Search, ShieldAlert } from "lucide-react";
import { $api } from "@/lib/api";
import type { components } from "@/lib/schema";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";

type Ticket = components["schemas"]["TicketSummary"];
const PREVIEW_KEY = "tickets.preview";
type Detail = components["schemas"]["TicketDetail"];

const statusStyle: Record<Ticket["status"], string> = {
  queued: "bg-muted text-muted-foreground", running: "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
  needs_approval: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  done: "bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300",
  failed: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
};
const statusName: Record<Ticket["status"], string> = {
  queued: "Queued", running: "Investigating", needs_approval: "Needs approval", done: "Done", failed: "Failed",
};
function human(value: string | null | undefined) { return value?.replaceAll("_", " ") ?? "—"; }
function duration(ticket: Ticket) {
  const seconds = differenceInSeconds(ticket.completed_at ?? new Date(), ticket.received_at);
  return seconds < 60 ? `${Math.max(seconds, 0)}s` : `${Math.floor(seconds / 60)}m`;
}

function Preview({ ticket }: { ticket: Detail | undefined }) {
  if (!ticket) return <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm text-muted-foreground"><Inbox size={20} />Select a ticket</div>;
  const initials = ticket.tenant_id?.split(/[-_\s]+/).map((part) => part[0]?.toUpperCase()).join("").slice(0, 2) || "?";
  return <div className="flex h-full min-h-0 flex-col">
    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain p-5">
      <div><p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Ticket preview</p><p className="mt-4 font-mono text-xs text-muted-foreground">#{ticket.id}</p><h2 className="mt-1 text-base font-semibold leading-snug">{ticket.subject}</h2><Badge variant="outline" className={`mt-3 gap-1 border-transparent ${statusStyle[ticket.status]}`}>{ticket.status === "running" && <LoaderCircle size={11} className="animate-spin" />}{ticket.status === "done" && <Check size={11} />}{ticket.status === "needs_approval" && <ShieldAlert size={11} />}{statusName[ticket.status]}</Badge></div>
      <Separator />
      <section><h3 className="mb-3 text-sm font-medium">Customer</h3><div className="flex items-center gap-2.5"><Avatar><AvatarFallback className="bg-blue-50 text-xs font-semibold text-blue-700 dark:bg-blue-950 dark:text-blue-300">{initials}</AvatarFallback></Avatar><span className="text-sm font-medium">{ticket.tenant_id ?? "Unknown tenant"}</span></div></section>
      <Separator />
      <dl className="grid grid-cols-[85px_1fr] gap-y-2.5 text-xs"><dt className="text-muted-foreground">Lane</dt><dd className="capitalize">{human(ticket.lane)}</dd><dt className="text-muted-foreground">Severity</dt><dd>{ticket.severity ? <Badge variant="outline" className={ticket.severity <= 2 ? "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300" : ""}>Sev {ticket.severity}</Badge> : "—"}</dd><dt className="text-muted-foreground">Current stage</dt><dd className="capitalize">{human(ticket.current_stage)}</dd></dl>
      <Separator />
      <section><h3 className="mb-2 text-sm font-medium">Customer message</h3><p className="rounded-md bg-muted/60 p-3 text-sm leading-relaxed whitespace-pre-wrap">{ticket.body}</p></section>
      {ticket.jev && <><Separator /><section><h3 className="mb-3 text-sm font-medium">Classification</h3><div className="space-y-3">{ticket.jev.answers.map((answer) => <div key={answer.question}><div className="mb-1 flex justify-between gap-2 text-xs"><span className="capitalize text-muted-foreground">{human(answer.question)}</span><span>{String(answer.answer)}</span></div><Progress value={answer.confidence * 100} className="h-1" /></div>)}</div></section></>}
      {ticket.outcome && <><Separator /><section><h3 className="mb-2 text-sm font-medium">Final result</h3><p className="text-sm leading-relaxed">{ticket.outcome.summary}</p></section></>}
    </div>
    <div className="shrink-0 border-t bg-background p-4"><Button asChild className="w-full"><Link href={`/ticket/${encodeURIComponent(ticket.id)}`}>Open investigation <ArrowRight size={15} /></Link></Button></div>
  </div>;
}

export default function TicketsPage() {
  const router = useRouter();
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobilePreview, setMobilePreview] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(true);
  const [previewAnimates, setPreviewAnimates] = useState(false); // not while restoring the saved state
  const [createOpen, setCreateOpen] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [tenant, setTenant] = useState("figma-merch");
  const tableScroll = useRef<HTMLDivElement>(null);
  const create = $api.useMutation("post", "/simulator/tickets");
  async function createTicket(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!subject.trim() || !body.trim() || !tenant.trim()) return;
    try {
      const result = await create.mutateAsync({ body: { subject: subject.trim(), body: body.trim(), tenant_id: tenant.trim(), requester: null } });
      if (typeof result.ticket_id !== "string") throw new Error("Ticket ID missing from response");
      setCreateOpen(false);
      router.push(`/ticket/${encodeURIComponent(result.ticket_id)}`);
    } catch { toast.error("Could not create the ticket. Check the API connection and try again."); }
  }
  useEffect(() => {
    try { if (localStorage.getItem(PREVIEW_KEY) === "closed") setPreviewOpen(false); } catch {}
    const frame = requestAnimationFrame(() => setPreviewAnimates(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  function togglePreview(open: boolean) {
    setPreviewOpen(open);
    try { localStorage.setItem(PREVIEW_KEY, open ? "open" : "closed"); } catch {}
  }
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1280px)");
    const closeOnDesktop = () => { if (desktop.matches) setMobilePreview(false); };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);
  const { data: tickets, isLoading, error } = $api.useQuery("get", "/tickets", {}, { refetchInterval: 2000 });
  const selected = selectedId ?? tickets?.[0]?.id ?? "";
  const { data: detail } = $api.useQuery("get", "/tickets/{ticket_id}", { params: { path: { ticket_id: selected } } }, { enabled: Boolean(selected), refetchInterval: 2000 });
  const rows = useMemo(() => (tickets ?? []).filter((ticket) => {
    const match = `${ticket.id} ${ticket.subject} ${ticket.tenant_id ?? ""}`.toLowerCase().includes(search.toLowerCase());
    return match && (filter === "all" || ticket.status === filter);
  }), [tickets, search, filter]);
  const columns = useMemo<ColumnDef<Ticket>[]>(() => [
    { header: "Ticket", accessorKey: "id", cell: ({ row }) => <div><div className="font-medium">#{row.original.id}</div><div className="max-w-56 truncate text-xs text-muted-foreground">{row.original.subject}</div></div> },
    { header: "Tenant", accessorKey: "tenant_id", cell: ({ row }) => <span className="text-sm">{row.original.tenant_id ?? "—"}</span> },
    { header: "Lane", accessorKey: "lane", cell: ({ row }) => <span className="capitalize text-muted-foreground">{human(row.original.lane)}</span> },
    { header: "Current stage", accessorKey: "current_stage", cell: ({ row }) => <span className="inline-flex items-center gap-1.5 capitalize text-muted-foreground">{row.original.status === "running" && <LoaderCircle size={12} className="animate-spin text-blue-600" />}{human(row.original.current_stage)}</span> },
    { header: "Severity", accessorKey: "severity", cell: ({ row }) => row.original.severity ? <Badge variant="outline" className={row.original.severity <= 2 ? "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300" : ""}>Sev {row.original.severity}</Badge> : "—" },
    { header: "Status", accessorKey: "status", cell: ({ row }) => <Badge variant="outline" className={`gap-1 border-transparent ${statusStyle[row.original.status]}`}>{row.original.status === "running" && <LoaderCircle size={11} className="animate-spin" />}{row.original.status === "done" && <Check size={11} />}{row.original.status === "needs_approval" && <ShieldAlert size={11} />}{statusName[row.original.status]}</Badge> },
    { header: "Duration", id: "duration", cell: ({ row }) => <span className="text-muted-foreground">{duration(row.original)}</span> },
    { header: "Cost", accessorKey: "cost_usd", cell: ({ row }) => <span className="text-muted-foreground">${row.original.cost_usd.toFixed(3)}</span> },
    { header: "Received", accessorKey: "received_at", cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{formatDistanceToNow(row.original.received_at, { addSuffix: true })}</span> },
  ], []);
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });
  return <div className="flex min-h-screen min-w-0">
    <main className="min-w-0 flex-1 px-6 py-7 xl:px-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4"><div className="min-w-40 flex-1"><div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground"><Clock3 size={13} /> Live queue</div><h1 className="text-xl font-semibold tracking-tight">Tickets</h1><p className="mt-1 text-xs text-muted-foreground">Support investigations{tickets ? ` · ${tickets.length} total` : ""}</p></div><div className="flex w-full flex-wrap items-center gap-2 sm:w-auto"><div className="relative min-w-48 flex-1 sm:w-56 sm:flex-none"><Search className="absolute top-2.5 left-3 size-4 text-muted-foreground" /><Input aria-label="Search tickets" placeholder="Search tickets..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" /></div><Dialog open={createOpen} onOpenChange={setCreateOpen}><DialogTrigger asChild><Button size="sm"><Plus size={15} /> New ticket</Button></DialogTrigger><DialogContent className="sm:max-w-lg"><DialogHeader><DialogTitle>New ticket</DialogTitle><DialogDescription>Create a ticket and start its investigation. You’ll go straight to the live activity.</DialogDescription></DialogHeader><form onSubmit={createTicket} className="space-y-4"><div><label htmlFor="new-ticket-tenant" className="mb-1.5 block text-xs font-medium">Tenant ID</label><Input id="new-ticket-tenant" value={tenant} onChange={(event) => setTenant(event.target.value)} required /></div><div><label htmlFor="new-ticket-subject" className="mb-1.5 block text-xs font-medium">Subject</label><Input id="new-ticket-subject" value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="A short summary of the issue" required /></div><div><label htmlFor="new-ticket-body" className="mb-1.5 block text-xs font-medium">Customer message</label><Textarea id="new-ticket-body" value={body} onChange={(event) => setBody(event.target.value)} placeholder="Describe the customer’s issue…" className="min-h-36 resize-y" required /></div><DialogFooter><Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={create.isPending}>Cancel</Button><Button type="submit" disabled={create.isPending || !subject.trim() || !body.trim() || !tenant.trim()}>{create.isPending ? <LoaderCircle size={15} className="animate-spin" /> : <ArrowRight size={15} />}{create.isPending ? "Creating…" : "Create and investigate"}</Button></DialogFooter></form></DialogContent></Dialog></div></div>
      <div className="mb-4 flex items-center justify-between gap-2"><Tabs value={filter} onValueChange={setFilter}><TabsList variant="line"><TabsTrigger value="all">All</TabsTrigger><TabsTrigger value="running">Running</TabsTrigger><TabsTrigger value="needs_approval">Needs approval</TabsTrigger><TabsTrigger value="done">Done</TabsTrigger></TabsList></Tabs><div className="flex shrink-0 items-center gap-1"><Button variant="ghost" size="icon-xs" aria-label="Scroll tickets left" onClick={() => tableScroll.current?.querySelector<HTMLElement>('[data-slot="table-container"]')?.scrollBy({ left: -350, behavior: "smooth" })}><ChevronLeft size={14} /></Button><Button variant="ghost" size="icon-xs" aria-label="Scroll tickets right" onClick={() => tableScroll.current?.querySelector<HTMLElement>('[data-slot="table-container"]')?.scrollBy({ left: 350, behavior: "smooth" })}><ChevronRight size={14} /></Button></div></div>
      {isLoading ? <div className="space-y-3">{Array.from({ length: 7 }, (_, i) => <Skeleton key={i} className="h-14 w-full" />)}</div> : error ? <div className="flex flex-col items-center gap-2 py-20 text-center text-sm text-destructive"><ShieldAlert size={20} />Could not load tickets. Check the API connection.</div> : rows.length === 0 ? <div className="flex flex-col items-center gap-2 py-20 text-center text-sm text-muted-foreground"><Inbox size={20} />No tickets found.</div> : <div ref={tableScroll} className="overflow-x-auto rounded-md border"><Table><TableHeader>{table.getHeaderGroups().map((group) => <TableRow key={group.id}>{group.headers.map((header) => <TableHead key={header.id}>{typeof header.column.columnDef.header === "string" ? header.column.columnDef.header : ""}</TableHead>)}</TableRow>)}</TableHeader><TableBody>{table.getRowModel().rows.map((row) => <TableRow key={row.id} data-state={selected === row.original.id ? "selected" : undefined} className="h-[60px] cursor-pointer transition-colors hover:bg-muted/40 data-[state=selected]:bg-blue-50/60 dark:data-[state=selected]:bg-blue-950/20" onClick={() => { setSelectedId(row.original.id); if (window.matchMedia("(max-width: 1279px)").matches) setMobilePreview(true); else togglePreview(true); }}>{row.getVisibleCells().map((cell) => <TableCell key={cell.id}>{typeof cell.column.columnDef.cell === "function" ? cell.column.columnDef.cell(cell.getContext()) : cell.getValue() as React.ReactNode}</TableCell>)}</TableRow>)}</TableBody></Table></div>}
    </main>
    <aside className={`sticky top-0 hidden h-svh shrink-0 self-start overflow-hidden border-l xl:block ${previewAnimates ? "transition-[width] duration-200 ease-out" : ""} ${previewOpen ? "w-[310px]" : "w-11"}`}>
      {previewOpen
        ? <div className="relative h-full w-[310px]"><Button variant="ghost" size="icon" className="absolute top-3 right-3 z-10 size-7 text-muted-foreground" aria-label="Collapse ticket preview" aria-expanded title="Collapse preview" onClick={() => togglePreview(false)}><PanelRightClose size={15} /></Button><Preview ticket={detail} /></div>
        : <button type="button" className="flex h-full w-11 flex-col items-center gap-3 pt-3 text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground" aria-label="Expand ticket preview" aria-expanded={false} title="Expand preview" onClick={() => togglePreview(true)}><span className="flex size-7 items-center justify-center rounded-md"><PanelRightOpen size={15} /></span><span className="text-[11px] font-semibold tracking-wider uppercase [writing-mode:vertical-rl]">Ticket preview</span></button>}
    </aside>
    <Sheet open={mobilePreview} onOpenChange={setMobilePreview}><SheetContent className="p-0 xl:hidden"><SheetHeader className="sr-only"><SheetTitle>Ticket preview</SheetTitle></SheetHeader><Preview ticket={detail} /></SheetContent></Sheet>
  </div>;
}
