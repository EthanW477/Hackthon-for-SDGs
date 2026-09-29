"use client";

import { AlertTriangle, CheckCircle2, Lightbulb, X, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { FlightPlanCheckResponse } from "@/lib/api";

const SUGGESTION_KIND_LABELS: Record<string, string> = {
  reroute: "Reroute",
  lower_altitude: "Lower altitude",
  reschedule: "Reschedule",
  change_aircraft: "Change aircraft",
};

interface VerdictCardProps {
  result: FlightPlanCheckResponse;
  onClose: () => void;
}

/**
 * Compact verdict card for a flight-plan check: approved/rejected badge,
 * rule violations (with regulation references), and counterfactual
 * suggestions. Map-linked: red segments / green alternatives stay on the
 * globe after the card is dismissed.
 */
export default function VerdictCard({ result, onClose }: VerdictCardProps) {
  const approved = result.verdict === "approved";
  return (
    <Card className="absolute right-3 bottom-6 z-10 max-h-[55%] w-80 max-w-[calc(100vw-2rem)] gap-2 overflow-y-auto bg-background/95 py-3 backdrop-blur">
      <CardHeader>
        <div className="flex items-center gap-2">
          {approved ? (
            <CheckCircle2 className="size-4 shrink-0 text-emerald-500" />
          ) : (
            <XCircle className="size-4 shrink-0 text-red-500" />
          )}
          <CardTitle>Flight plan check</CardTitle>
          <span
            className={
              approved
                ? "rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-600 dark:text-emerald-400"
                : "rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-semibold text-red-600 dark:text-red-400"
            }
          >
            {approved ? "Approved" : "Rejected"}
          </span>
        </div>
        <Button size="icon-xs" variant="ghost" onClick={onClose} aria-label="Dismiss verdict">
          <X />
        </Button>
      </CardHeader>

      <CardContent className="space-y-3">
        {approved && result.violations.length === 0 && (
          <p className="text-xs text-muted-foreground">
            Route complies with all checked rules (altitude ceiling, RFZ intersection,
            separation, aircraft category, time window).
          </p>
        )}

        {result.violations.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Violations
            </div>
            <ul className="space-y-1.5">
              {result.violations.map((v, i) => (
                <li key={i} className="flex gap-2 text-xs">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-red-500" />
                  <div>
                    <span className="mr-1 rounded bg-red-500/10 px-1 py-0.5 font-mono text-[10px] font-medium text-red-600 dark:text-red-400">
                      {v.regulation_ref}
                    </span>
                    {v.segment_index != null && (
                      <span className="mr-1 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
                        segment {v.segment_index + 1}
                      </span>
                    )}
                    <span>{v.message}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {result.suggestions.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Suggestions
            </div>
            <ul className="space-y-1.5">
              {result.suggestions.map((s, i) => (
                <li key={i} className="flex gap-2 text-xs">
                  <Lightbulb className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
                  <div>
                    <span className="mr-1 rounded bg-emerald-500/10 px-1 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                      {SUGGESTION_KIND_LABELS[s.kind] ?? s.kind}
                    </span>
                    <span>{s.description}</span>
                    {s.patched_route_geojson && (
                      <span className="ml-1 text-emerald-600 dark:text-emerald-400">
                        — shown in green on the map
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
