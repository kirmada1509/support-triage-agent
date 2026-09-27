"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_URL } from "./api";
import type { components } from "./schema";

type StoredEvent = components["schemas"]["StoredEvent"];
type StageEvent = components["schemas"]["StageEvent"];

const kinds: StoredEvent["event"]["kind"][] = [
  "stage", "tool_call", "model_delta", "model_output", "retrieval", "jev",
  "approval_required", "link", "delivery", "outcome", "error",
];

export function useTicketEvents(ticketId: string, replay: boolean) {
  const queryClient = useQueryClient();
  const key = useMemo(() => ["ticket-events", ticketId, replay] as const, [ticketId, replay]);
  const { data: events = [] } = useQuery<StoredEvent[]>({
    queryKey: key,
    queryFn: () => [],
    initialData: [],
    staleTime: Infinity,
  });
  const [isConnected, setConnected] = useState(false);

  useEffect(() => {
    queryClient.setQueryData<StoredEvent[]>(key, []);
    const source = new EventSource(
      `${API_URL}/tickets/${encodeURIComponent(ticketId)}/events/stream${replay ? "?replay=1" : ""}`,
    );
    source.onopen = () => setConnected(true);
    source.onerror = () => {
      setConnected(false);
      if (replay) source.close();
    };
    const receive = (message: MessageEvent<string>) => {
      const incoming = JSON.parse(message.data) as StoredEvent;
      queryClient.setQueryData<StoredEvent[]>(key, (current = []) =>
        current.some((event) => event.id === incoming.id) ? current : [...current, incoming],
      );
    };
    for (const kind of kinds) source.addEventListener(kind, receive as EventListener);
    return () => {
      for (const kind of kinds) source.removeEventListener(kind, receive as EventListener);
      source.close();
      setConnected(false);
    };
  }, [ticketId, replay, queryClient, key]);

  const eventsByStage = useMemo(() => {
    const grouped: Record<string, StoredEvent[]> = {};
    for (const item of events) {
      const stage = item.event.stage;
      if (stage) (grouped[stage] ??= []).push(item);
    }
    return grouped;
  }, [events]);
  const stageStatuses = useMemo(() => {
    const latest: Record<string, StageEvent> = {};
    for (const item of events) {
      if (item.event.kind === "stage") latest[item.event.stage] = item.event;
    }
    return latest;
  }, [events]);
  const activeStage = [...events].reverse().find((item) =>
    item.event.kind === "stage" && item.event.status === "running" &&
      stageStatuses[item.event.stage]?.status === "running",
  );

  return {
    events,
    eventsByStage,
    stageStatuses,
    activeStage: activeStage?.event.stage ?? null,
    isConnected,
    isReplaying: replay,
  };
}
