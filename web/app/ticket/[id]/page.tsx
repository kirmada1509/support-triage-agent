import { Suspense } from "react";
import TicketScreen from "./ticket-screen";

export default function TicketPage() {
  return <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Loading investigation…</div>}><TicketScreen /></Suspense>;
}
