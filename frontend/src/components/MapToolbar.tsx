"use client";

import { Layers, Loader2, Pencil, RotateCcw, Send, Trash2, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

interface MapToolbarProps {
  rfzVisible: boolean;
  onRfzVisibleChange: (visible: boolean) => void;
  rfzError: string | null;
  drawActive: boolean;
  onDrawActiveChange: (active: boolean) => void;
  pointCount: number;
  altitudeFt: number;
  onAltitudeFtChange: (ft: number) => void;
  onUndo: () => void;
  onClear: () => void;
  onSubmit: () => void;
  submitting: boolean;
  submitError: string | null;
  verdict: "approved" | "rejected" | null;
  onReopenVerdict: () => void;
}

/** Floating map controls: RFZ layer switch + route drawing / submission. */
export default function MapToolbar({
  rfzVisible,
  onRfzVisibleChange,
  rfzError,
  drawActive,
  onDrawActiveChange,
  pointCount,
  altitudeFt,
  onAltitudeFtChange,
  onUndo,
  onClear,
  onSubmit,
  submitting,
  submitError,
  verdict,
  onReopenVerdict,
}: MapToolbarProps) {
  return (
    <Card className="absolute top-3 left-3 z-10 w-64 max-w-[calc(100vw-2rem)] gap-3 bg-background/90 py-3 backdrop-blur">
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          <Layers className="size-3.5" />
          Layers
        </div>
        <label className="flex items-center justify-between gap-2 text-sm">
          <span className="flex items-center gap-2">
            <span className="inline-block size-2.5 rounded-sm bg-[#ff3b30]/70 ring-1 ring-[#ff2d20]" />
            Restricted Flying Zones
          </span>
          <Switch checked={rfzVisible} onCheckedChange={onRfzVisibleChange} />
        </label>
        {rfzError && (
          <p className="text-xs text-destructive">RFZ layer failed to load: {rfzError}</p>
        )}

        <div className="border-t" />

        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Route check
          </span>
          {verdict && (
            <button
              type="button"
              onClick={onReopenVerdict}
              className={
                verdict === "approved"
                  ? "rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400"
                  : "rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-600 dark:text-red-400"
              }
            >
              {verdict === "approved" ? "Approved" : "Rejected"}
            </button>
          )}
        </div>

        {!drawActive && pointCount === 0 ? (
          <Button size="sm" className="w-full" onClick={() => onDrawActiveChange(true)}>
            <Pencil data-icon="inline-start" />
            Draw route
          </Button>
        ) : (
          <div className="space-y-2">
            {drawActive && (
              <p className="text-xs text-muted-foreground">
                Click the map to add waypoints — {pointCount} placed
                {pointCount < 2 ? " (need at least 2)" : ""}.
              </p>
            )}
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              Altitude (ft)
              <Input
                type="number"
                min={1}
                step={10}
                value={altitudeFt}
                onChange={(e) => onAltitudeFtChange(Number(e.target.value))}
                className="h-7 w-24"
              />
            </label>
            <div className="flex gap-1.5">
              <Button
                size="sm"
                variant="outline"
                onClick={onUndo}
                disabled={pointCount === 0 || submitting}
              >
                <Undo2 data-icon="inline-start" />
                Undo
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={onClear}
                disabled={pointCount === 0 || submitting}
              >
                <Trash2 data-icon="inline-start" />
                Clear
              </Button>
              {drawActive ? (
                <Button
                  size="sm"
                  className="flex-1"
                  onClick={onSubmit}
                  disabled={pointCount < 2 || submitting}
                >
                  {submitting ? (
                    <Loader2 data-icon="inline-start" className="animate-spin" />
                  ) : (
                    <Send data-icon="inline-start" />
                  )}
                  Check
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="secondary"
                  className="flex-1"
                  onClick={() => onDrawActiveChange(true)}
                >
                  <RotateCcw data-icon="inline-start" />
                  Edit
                </Button>
              )}
            </div>
            {submitError && <p className="text-xs text-destructive">{submitError}</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
