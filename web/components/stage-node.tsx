"use client";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { Check, Circle, Clock3, LoaderCircle, Minus, X } from "lucide-react";
import { BaseNode } from "@/components/base-node";
import { NodeStatusIndicator } from "@/components/node-status-indicator";
import type { components } from "@/lib/schema";

export type StageNodeData = {
  label: string;
  status: components["schemas"]["StageEvent"]["status"];
  approvalWaiting?: boolean;
};
export type StageFlowNode = Node<StageNodeData, "stage">;

export function StageNode({ data }: NodeProps<StageFlowNode>) {
  const icon = data.approvalWaiting ? <Clock3 size={13} /> : data.status === "done" ? <Check size={13} /> : data.status === "running" ? <LoaderCircle size={13} className="animate-spin" /> : data.status === "failed" ? <X size={13} /> : data.status === "skipped" ? <Minus size={13} /> : <Circle size={12} />;
  const color = data.approvalWaiting ? "text-amber-700 dark:text-amber-300" : data.status === "done" ? "text-green-600" : data.status === "running" ? "text-blue-600" : data.status === "failed" ? "text-red-600" : "text-muted-foreground";
  return <NodeStatusIndicator status={data.status === "failed" ? "error" : "initial"}>
    <BaseNode className={`w-[100px] px-2 py-1 shadow-none ${data.status === "skipped" ? "opacity-40" : ""} ${data.status === "running" && !data.approvalWaiting ? "border-blue-400 bg-blue-50/50 dark:bg-blue-950/20" : ""} ${data.approvalWaiting ? "border-amber-300 bg-amber-50/50 dark:border-amber-900 dark:bg-amber-950/20" : ""} ${data.status === "done" ? "border-green-200 dark:border-green-900" : ""}`}>
      <Handle type="target" position={Position.Left} className="!invisible" />
      <div className={`flex items-center gap-1.5 text-[11px] font-medium capitalize ${color}`}>{icon}<span className="truncate">{data.label}</span></div>
      <div className="ml-5 text-[10px] capitalize text-muted-foreground">{data.approvalWaiting ? "Approval needed" : data.status === "waiting" ? "Pending" : data.status}</div>
      <Handle type="source" position={Position.Right} className="!invisible" />
    </BaseNode>
  </NodeStatusIndicator>;
}
