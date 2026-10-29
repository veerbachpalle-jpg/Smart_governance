import { useSuspenseQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  ArrowUpRight,
  Plus,
  Files,
  LoaderCircle,
  ClipboardCheck,
  CheckCheck,
  MapPin,
  ShieldCheck,
  Clock3,
  Check,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { complaintsQuery, PageHeading, ComplaintTable, categories, StatusBadge, CategoryIcon } from "./shared";
import LocationMap, { getDepartmentColor } from "./LocationMap";
import { civicApi } from "@/lib/civic-api";
import { toast } from "sonner";
import { PopularIssuesNearYou } from "./CitizenPages";
import type { Complaint } from "@/lib/civic-types";

export default function Overview() {
  const { data: rows } = useSuspenseQuery(complaintsQuery);
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [tracking, setTracking] = useState("");

  // Reopen/Challenge Dialog state
  const [reopenTarget, setReopenTarget] = useState<Complaint | null>(null);
  const [reopenReason, setReopenReason] = useState("");
  const [busyAction, setBusyAction] = useState(false);

  // Filter complaints in the 7-day review window or recently resolved
  const reviewAwaiting = rows.filter((row) => row.status === "review");
  const recentlySolved = rows.filter((row) => row.status === "resolved");

  const metrics = [
    {
      label: "total",
      title: "All Complaints",
      count: rows.length,
      icon: Files,
      caption: "All neighbourhood & personal reports",
      tone: "text-muted-foreground bg-muted",
    },
    {
      label: "active",
      title: "In Progress",
      count: rows.filter((row) => row.status === "in_progress").length,
      icon: LoaderCircle,
      caption: "Active department remediation",
      tone: "text-info bg-info-soft",
    },
    {
      label: "awaiting",
      title: "7-Day Review",
      count: reviewAwaiting.length,
      icon: ClipboardCheck,
      caption: "Citizen satisfaction confirmation needed",
      tone: "text-warning bg-warning-soft",
    },
    {
      label: "resolved",
      title: "Solved & Closed",
      count: recentlySolved.length,
      icon: CheckCheck,
      caption: "Citizen confirmed & verified",
      tone: "text-success bg-success-soft",
    },
  ];

  async function handleConfirmSatisfaction(row: Complaint) {
    setBusyAction(true);
    try {
      await civicApi.update(row.id, { note: "Citizen verified satisfaction with resolution." }, "confirm");
      toast.success(`Resolution for ${row.id} confirmed and closed!`);
      await queryClient.invalidateQueries({ queryKey: ["complaints"] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Confirmation failed.");
    } finally {
      setBusyAction(false);
    }
  }

  async function handleReopenCase() {
    if (!reopenTarget || reopenReason.trim().length < 8) {
      toast.error("Please provide at least 8 characters explaining why the issue is not resolved.");
      return;
    }
    setBusyAction(true);
    try {
      await civicApi.update(
        reopenTarget.id,
        { status: "challenged", challenge: { reason: reopenReason, evidence: [] } },
        "challenge",
      );
      toast.success(`Case ${reopenTarget.id} reopened and routed back to department lead!`);
      setReopenTarget(null);
      setReopenReason("");
      await queryClient.invalidateQueries({ queryKey: ["complaints"] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to reopen case.");
    } finally {
      setBusyAction(false);
    }
  }

  return (
    <div className="page-container fade-in">
      <PageHeading
        title="Citizen Dashboard"
        subtitle="Neighbourhood grievance map, real-time department tracking, and 7-day resolution satisfaction review."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild variant="outline" className="h-10 text-xs">
              <Link to="/complaints">
                <Files className="size-4 mr-1.5" />
                All Complaints ({rows.length})
              </Link>
            </Button>
            <Button asChild className="h-10 px-4 text-xs font-semibold">
              <Link to="/report">
                <Plus className="size-4 mr-1.5" />
                Submit New Complaint
              </Link>
            </Button>
          </div>
        }
      />

      {/* Hero Welcome Banner */}
      <div className="civic-banner mb-7 rounded-lg">
        <div className="relative z-10 max-w-2xl">
          <span className="section-label text-primary font-bold tracking-wider">
            SMART CIVIC GOVERNANCE · CITIZEN FIRST
          </span>
          <h2 className="mt-2 text-[22px] font-bold text-foreground">
            Explore Your Neighbourhood & Review Problem Resolutions
          </h2>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            View nearby complaints across all departments on the live interactive map below. Whenever an issue in your ward is marked resolved by department officers, you have up to <strong>7 days</strong> to test the fix and either <strong>confirm satisfaction</strong> or <strong>reopen the case</strong>.
          </p>
        </div>
        <div className="relative z-10 flex flex-wrap gap-2.5">
          <Button asChild variant="outline" className="h-10 border-primary/25 bg-surface px-4 text-primary text-xs">
            <Link to="/complaints">
              View All Complaints
              <ArrowRight className="ml-1 size-3.5" />
            </Link>
          </Button>
          <Button asChild className="h-10 px-4 text-xs">
            <Link to="/report">
              Report An Issue
              <Plus className="ml-1 size-3.5" />
            </Link>
          </Button>
        </div>
      </div>

      {/* 7-DAY REVIEW WINDOW ALERT BANNER (If any complaint is in 'review') */}
      {reviewAwaiting.length > 0 && (
        <section className="mb-7 rounded-lg border-2 border-warning/40 bg-warning-soft p-5 shadow-xs">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <span className="grid size-9 place-items-center rounded-lg bg-warning/20 text-warning">
                <Clock3 className="size-5" />
              </span>
              <div>
                <h3 className="text-sm font-bold text-warning-foreground">
                  7-Day Citizen Resolution Review Window ({reviewAwaiting.length} pending)
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  The municipal department has marked an issue solved. Please inspect the site and confirm whether you are satisfied, or reopen the case.
                </p>
              </div>
            </div>
            <span className="rounded-full bg-warning/20 px-3 py-1 text-xs font-semibold text-warning">
              Action Required within 7 Days
            </span>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {reviewAwaiting.map((row) => {
              const deadline = row.resolution?.deadline
                ? new Date(row.resolution.deadline)
                : new Date(Date.now() + 7 * 86400000);
              const daysLeft = Math.max(
                0,
                Math.ceil((deadline.getTime() - Date.now()) / 86400000),
              );
              return (
                <div
                  key={row.id}
                  className="rounded-md border border-warning/30 bg-surface p-4 flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-[11px] font-bold text-primary">{row.id}</span>
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-warning-soft text-warning">
                        ⏱ {daysLeft} {daysLeft === 1 ? "day" : "days"} left
                      </span>
                    </div>
                    <Link
                      to="/complaints/$id"
                      params={{ id: row.id }}
                      className="text-sm font-bold text-foreground hover:text-primary hover:underline line-clamp-1"
                    >
                      {row.title}
                    </Link>
                    <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
                      <strong>Officer Remediation:</strong>{" "}
                      {row.resolution?.notes || "Remediation works submitted for citizen approval."}
                    </p>
                    <p className="mt-1.5 text-[11px] text-muted-foreground">
                      <strong>Department:</strong> {row.department} · {row.ward}
                    </p>
                  </div>

                  <div className="mt-4 pt-3 border-t border-border flex flex-wrap items-center justify-between gap-2">
                    <Link
                      to="/complaints/$id"
                      params={{ id: row.id }}
                      className="text-xs font-medium text-primary hover:underline flex items-center gap-1"
                    >
                      Full Details & Timeline
                      <ArrowUpRight className="size-3" />
                    </Link>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-8 px-2.5 text-xs text-destructive hover:bg-destructive/10 border-destructive/30"
                        disabled={busyAction}
                        onClick={() => setReopenTarget(row)}
                      >
                        <RotateCcw className="size-3 mr-1" />
                        Reopen Case
                      </Button>
                      <Button
                        size="sm"
                        className="h-8 px-3 text-xs bg-success hover:bg-success/90 text-success-foreground"
                        disabled={busyAction}
                        onClick={() => handleConfirmSatisfaction(row)}
                      >
                        <Check className="size-3 mr-1" />
                        Confirm Satisfied
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Metrics Row */}
      <div className="mb-8 grid grid-cols-2 gap-4 xl:grid-cols-4">
        {metrics.map((metric) => (
          <div className="metric-card" key={metric.label}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-bold text-muted-foreground">{metric.title}</span>
              <div className={`grid size-8 shrink-0 place-items-center rounded-md ${metric.tone}`}>
                <metric.icon className="size-4" />
              </div>
            </div>
            <p className="mt-3 font-display text-[32px] font-bold leading-none">
              {String(metric.count).padStart(2, "0")}
            </p>
            <p className="mt-3 text-[10px] text-muted-foreground">{metric.caption}</p>
          </div>
        ))}
      </div>

      {/* PRIMARY FEATURE: NEIGHBOURS MAP */}
      <section className="panel mb-8 p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <MapPin className="size-5 text-primary" />
              <h2 className="text-base font-bold text-foreground">Neighbours & Ward Map</h2>
              <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-[10px] font-semibold text-primary">
                Multi-Department Live View
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Displays all nearby complaints from different municipal departments with distinct pin colors. Click on any pin to view event details and progress remarks.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground font-medium">
              {rows.length} total municipal reports plotted
            </span>
          </div>
        </div>

        {/* Large Multi-Department Leaflet Map with Legend */}
        <LocationMap complaints={rows} large showLegend />
      </section>

      {/* Two Column Section: Recent Problem Solved & Quick Tracking / Categories */}
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          {/* Recents: Problem Solved & Verified Window */}
          <section className="panel">
            <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4 border-b border-border">
              <div className="flex items-center gap-2">
                <CheckCheck className="size-4 text-success" />
                <h2 className="text-sm font-bold">
                  Recents: Solved & Verified Complaints
                  <span className="ml-2 rounded bg-success/15 px-1.5 py-0.5 font-sans text-[10px] font-semibold text-success">
                    {recentlySolved.length} solved
                  </span>
                </h2>
              </div>
              <Link
                to="/complaints"
                className="flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
              >
                View all reports
                <ArrowRight className="size-3.5" />
              </Link>
            </div>

            {recentlySolved.length === 0 ? (
              <div className="p-5 text-center text-xs text-muted-foreground">
                No closed issues yet. Active remediation is in progress.
              </div>
            ) : (
              <div className="divide-y divide-border">
                {recentlySolved.slice(0, 3).map((complaint) => (
                  <div key={complaint.id} className="p-4 hover:bg-muted/30 transition-colors">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-start gap-3 min-w-0">
                        <div
                          className="mt-0.5 size-3 rounded-full shrink-0"
                          style={{ backgroundColor: getDepartmentColor(complaint.department) }}
                        />
                        <div className="min-w-0">
                          <Link
                            to="/complaints/$id"
                            params={{ id: complaint.id }}
                            className="text-xs font-bold text-foreground hover:text-primary truncate block"
                          >
                            {complaint.title}
                          </Link>
                          <p className="mt-1 text-[11px] text-muted-foreground line-clamp-1">
                            {complaint.description}
                          </p>
                          <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                            <span className="font-semibold text-foreground">{complaint.department}</span>
                            <span>·</span>
                            <span>{complaint.ward}</span>
                            <span>·</span>
                            <span className="text-success font-medium flex items-center gap-1">
                              <CheckCheck className="size-3" />
                              Citizen Satisfaction Verified
                            </span>
                          </div>
                        </div>
                      </div>
                      <Button asChild size="sm" variant="ghost" className="h-8 text-xs shrink-0">
                        <Link to="/complaints/$id" params={{ id: complaint.id }}>
                          Remarks & Timeline
                          <ArrowRight className="ml-1 size-3" />
                        </Link>
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* All Complaints Table Preview */}
          <section className="panel">
            <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-4 border-b border-border">
              <h2 className="text-sm font-bold">
                All Ward Complaints
                <span className="ml-2 rounded bg-muted px-1.5 py-0.5 font-sans text-[10px] font-medium text-muted-foreground">
                  {rows.length}
                </span>
              </h2>
              <Link
                to="/complaints"
                className="flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
              >
                {t("viewAll")}
                <ArrowRight className="size-3.5" />
              </Link>
            </div>
            <ComplaintTable rows={rows.slice(0, 4)} />
          </section>
        </div>

        {/* Right Column: Quick Track & Service Departments */}
        <div className="space-y-6">
          <PopularIssuesNearYou lat={rows[0]?.lat ?? 12.972} lng={rows[0]?.lng ?? 77.641} compact />

          <section className="panel p-5">
            <div className="mb-3 flex items-center gap-2">
              <ClipboardCheck className="size-4 text-primary" />
              <h2 className="text-xs font-bold">{t("quickTrack")}</h2>
            </div>
            <p className="text-[11px] text-muted-foreground mb-3">
              Enter any municipal tracking ID to check real-time SLA deadlines and official progress notes.
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!tracking.trim()) toast.error("Enter your tracking ID.");
              }}
            >
              <input
                aria-label="Tracking ID"
                className="form-field text-xs uppercase"
                value={tracking}
                onChange={(event) => setTracking(event.target.value.toUpperCase())}
                placeholder={t("trackingPlaceholder")}
              />
              <Button asChild variant="outline" className="mt-3 h-9 w-full text-xs font-medium">
                <Link to="/track" search={{ id: tracking }}>
                  {t("trackingButton")}
                  <ArrowRight className="size-3.5 ml-1" />
                </Link>
              </Button>
            </form>
          </section>

          <section className="panel p-5">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-xs font-bold">{t("serviceCategories")}</h2>
              <span className="text-[10px] text-muted-foreground">5 Municipal Wings</span>
            </div>
            <div className="grid grid-cols-2 gap-2.5">
              {categories.map((category) => (
                <Link
                  to="/report"
                  search={{ category: category.name }}
                  key={category.name}
                  className="group flex flex-col items-center justify-center gap-2 rounded-lg border border-border bg-surface p-3 text-center transition-colors hover:border-primary/40 hover:bg-secondary"
                >
                  <category.icon strokeWidth={1.5} className="size-5 text-primary" />
                  <span className="text-[11px] font-medium leading-tight">{category.name}</span>
                </Link>
              ))}
            </div>
          </section>

          <div className="flex items-start gap-3 rounded-lg border border-border bg-surface p-4">
            <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" />
            <div>
              <h3 className="text-xs font-bold">{t("accountability")}</h3>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                {t("accountabilityText")}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Modal Dialog for Reopening Case / Objecting */}
      <Dialog open={Boolean(reopenTarget)} onOpenChange={(open) => { if (!open) setReopenTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Object & Reopen Complaint</DialogTitle>
            <DialogDescription>
              If the physical issue is not satisfactorily repaired or has recurred, submit your objection within the 7-day review window. The case will be reopened and reviewed by department supervisors.
            </DialogDescription>
          </DialogHeader>

          {reopenTarget && (
            <div className="space-y-4 pt-2">
              <div className="rounded-md bg-muted p-3 text-xs">
                <p className="font-semibold text-foreground">{reopenTarget.title}</p>
                <p className="text-muted-foreground mt-0.5">
                  Tracking ID: {reopenTarget.id} · Department: {reopenTarget.department}
                </p>
              </div>

              <div>
                <label htmlFor="reopen-reason-input" className="block text-xs font-semibold mb-1.5">
                  Why are you dissatisfied with the resolution?
                </label>
                <textarea
                  id="reopen-reason-input"
                  rows={4}
                  className="form-field text-xs resize-none"
                  placeholder="Detail what is still defective or incomplete on site..."
                  value={reopenReason}
                  onChange={(e) => setReopenReason(e.target.value)}
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setReopenTarget(null);
                    setReopenReason("");
                  }}
                  disabled={busyAction}
                >
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={busyAction || reopenReason.trim().length < 8}
                  onClick={handleReopenCase}
                >
                  <RotateCcw className="size-3 mr-1" />
                  {busyAction ? "Reopening..." : "Reopen Case"}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

