"use client";

import { Coins } from "lucide-react";
import { $api } from "@/lib/api";

const LOW = 1; // below this many units of currency the balance is shown as low

function money(total: number, currency: string) {
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(total); }
  catch { return `${total.toFixed(2)} ${currency}`; }
}

export function CreditBalance() {
  const { data, isError, isLoading } = $api.useQuery("get", "/providers/deepseek/balance", {}, { refetchInterval: 60_000, retry: false });
  const first = data?.balances[0];
  const low = data?.available === false || (first !== undefined && first.total < LOW);
  const value = isLoading ? "…" : isError ? "Unavailable" : !data?.configured ? "No key" : first ? money(first.total, first.currency) : "—";
  const tone = isError || !data?.configured ? "text-muted-foreground" : low ? "text-amber-700 dark:text-amber-300" : "text-foreground";
  const dot = isError || !data?.configured ? "bg-muted-foreground/40" : low ? "bg-amber-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-2 rounded-md border bg-background px-2.5 py-1.5 text-[11px]" title={data?.available === false ? "DeepSeek reports the balance can't cover API calls" : "DeepSeek API credit left, refreshed every minute"}>
      <Coins size={13} className="shrink-0 text-muted-foreground" />
      <span className="text-muted-foreground">DeepSeek credit</span>
      <span className={`ml-auto flex items-center gap-1.5 font-medium tabular-nums ${tone}`}><span className={`size-1.5 rounded-full ${dot}`} />{value}</span>
    </div>
  );
}
