import { useState, useEffect, useCallback, useRef } from "react";
import { useSuspenseQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Search,
  Plus,
  ArrowRight,
  ArrowLeft,
  ArrowUp,
  Check,
  MapPin,
  Upload,
  X,
  ShieldCheck,
  AlertCircle,
  Save,
  ClipboardCheck,
  Clock3,
  Image,
  FileCheck2,
  Mic,
  LoaderCircle,
  RotateCcw,
  CheckCheck,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  complaintsQuery,
  ComplaintTable,
  PageHeading,
  StatusBadge,
  categories,
  CategoryIcon,
} from "./shared";
import LocationMap, { getDepartmentColor } from "./LocationMap";
import { civicApi, getSession, isDemo, request, setTokens, setDemoMode } from "@/lib/civic-api";
import { useOnline, distanceMeters } from "@/lib/civic-sim";
import type { Complaint, Category, Tokens, TrendingIssue } from "@/lib/civic-types";
const schema = z.object({
  title: z.string().min(8, "Use at least 8 characters for the title.").max(150),
  description: z.string().min(20, "Describe the issue in at least 20 characters.").max(5000),
  category: z.enum([
    "Roads & footpaths",
    "Water & drainage",
    "Street lighting",
    "Waste management",
    "Public safety",
  ]),
});
type DescriptionForm = z.infer<typeof schema>;
async function readPhotos(files: FileList | null): Promise<string[]> {
  if (!files) return [];
  const picked = Array.from(files);
  if (picked.length > 5) throw new Error("Choose up to 5 photos.");
  for (const file of picked) {
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type))
      throw new Error("Only JPG, PNG and WebP photos are supported.");
    if (file.size > 5 * 1024 * 1024) throw new Error("Each photo must be smaller than 5 MB.");
  }
  return Promise.all(
    picked.map(
      (file) =>
        new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () =>
            typeof reader.result === "string"
              ? resolve(reader.result)
              : reject(new Error("Could not read photo."));
          reader.onerror = () => reject(new Error("Could not read photo."));
          reader.readAsDataURL(file);
        }),
    ),
  );
}
export function PopularIssuesNearYou({
  lat,
  lng,
  compact = false,
}: {
  lat: number;
  lng: number;
  compact?: boolean;
}) {
  const [issues, setIssues] = useState<TrendingIssue[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true);
    civicApi
      .trending(lat, lng)
      .then((rows) => {
        if (active) setIssues(rows);
      })
      .catch(() => {
        if (active) setIssues([]);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [lat, lng]);
  async function toggle(issue: TrendingIssue) {
    const delta = issue.upvoted ? -1 : 1;
    setPending(issue.backendId);
    setIssues((rows) =>
      rows.map((row) =>
        row.backendId === issue.backendId
          ? { ...row, upvoted: !row.upvoted, upvoteCount: Math.max(0, row.upvoteCount + delta) }
          : row,
      ),
    );
    try {
      const result = await civicApi.toggleUpvote(issue, lat, lng);
      setIssues((rows) =>
        rows.map((row) =>
          row.backendId === issue.backendId
            ? { ...row, upvoted: result.upvoted, upvoteCount: result.upvote_count }
            : row,
        ),
      );
      toast.success(
        result.upvoted
          ? "You endorsed this issue. You will receive updates on its resolution."
          : "Your endorsement was removed.",
      );
    } catch (error) {
      setIssues((rows) => rows.map((row) => (row.backendId === issue.backendId ? issue : row)));
      toast.error(error instanceof Error ? error.message : "Could not update your endorsement.");
    } finally {
      setPending(null);
    }
  }
  return (
    <section
      className={`panel ${compact ? "p-4" : "mb-7 p-5"}`}
      aria-labelledby={compact ? "popular-issues-submit" : "popular-issues-home"}
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2
            id={compact ? "popular-issues-submit" : "popular-issues-home"}
            className="text-sm font-bold"
          >
            Popular Issues Near You
          </h2>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Open reports within 2 km, ranked by neighbors affected.
          </p>
        </div>
        <MapPin className="size-5 text-primary" />
      </div>
      {loading ? (
        <p className="text-xs text-muted-foreground">Finding nearby reports…</p>
      ) : issues.length === 0 ? (
        <p className="text-xs text-muted-foreground">No open reports were found nearby.</p>
      ) : (
        <div className="space-y-3">
          {issues.slice(0, compact ? 2 : 4).map((issue) => (
            <article
              key={issue.backendId}
              className="flex flex-wrap items-center gap-3 rounded-md border border-border p-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-semibold">{issue.title}</p>
                <p className="mt-1 text-[10px] text-muted-foreground">
                  {issue.ward} · {Math.round(issue.distanceMeters)} m away
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant={issue.upvoted ? "default" : "outline"}
                disabled={pending === issue.backendId}
                aria-pressed={issue.upvoted}
                onClick={() => toggle(issue)}
              >
                <ArrowUp />▲ {issue.upvoteCount} neighbors affected
              </Button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
export function ComplaintsPage() {
  const { data: rows } = useSuspenseQuery(complaintsQuery);
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  // Read initial tab from URL if present
  const getInitialTab = (): "all" | "mine" | "review" => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const tabParam = params.get("tab");
      if (tabParam === "mine" || tabParam === "review" || tabParam === "all") return tabParam;
    }
    return "all";
  };

  const [activeTab, setActiveTab] = useState<"all" | "mine" | "review">(getInitialTab());
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [department, setDepartment] = useState("all");

  // Reopen / challenge dialog state
  const [reopenTarget, setReopenTarget] = useState<Complaint | null>(null);
  const [reopenReason, setReopenReason] = useState("");
  const [busyAction, setBusyAction] = useState(false);

  // Identify My Complaints: from sessionStorage or default to first 2 demo items
  const myIds: string[] = (() => {
    if (typeof window === "undefined") return [];
    try {
      const stored = JSON.parse(sessionStorage.getItem("civic_my_complaints") || "[]");
      if (Array.isArray(stored) && stored.length > 0) return stored;
    } catch {
      // fallback
    }
    return [rows[0]?.id, rows[1]?.id].filter(Boolean);
  })();

  const myComplaints = rows.filter((r) => myIds.includes(r.id));
  const reviewAwaiting = rows.filter((r) => r.status === "review");
  const recentlySolved = rows.filter((r) => r.status === "resolved");
  const reviewTabRows = rows.filter((r) => ["review", "resolved", "challenged", "reopened"].includes(r.status));

  // Determine base list based on active tab
  const baseRows =
    activeTab === "mine"
      ? myComplaints
      : activeTab === "review"
        ? reviewTabRows
        : rows;

  const filtered = baseRows.filter((row) => {
    const matchesSearch = `${row.title} ${row.id} ${row.category} ${row.department} ${row.address}`
      .toLowerCase()
      .includes(search.toLowerCase());
    const matchesStatus = status === "all" || row.status === status;
    const matchesDept = department === "all" || row.department === department;
    return matchesSearch && matchesStatus && matchesDept;
  });

  const allDepts = Array.from(new Set(rows.map((r) => r.department).filter(Boolean)));

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
      toast.success(`Case ${reopenTarget.id} reopened and routed to supervisor!`);
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
        title="Civic Complaints"
        subtitle="Track municipal reports, follow accountable departments, and review solved cases within the 7-day review window."
        action={
          <Button asChild className="h-11 px-5">
            <Link to="/report">
              <Plus className="size-4 mr-1.5" />
              {t("newReport")}
            </Link>
          </Button>
        }
      />

      {/* Primary Tab Switcher */}
      <div className="mb-6 flex border-b border-border">
        <button
          type="button"
          onClick={() => setActiveTab("all")}
          className={`flex items-center gap-2 border-b-2 px-5 py-3 text-xs font-semibold transition-colors ${
            activeTab === "all"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <span>All Complaints</span>
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold text-muted-foreground">
            {rows.length}
          </span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("mine")}
          className={`flex items-center gap-2 border-b-2 px-5 py-3 text-xs font-semibold transition-colors ${
            activeTab === "mine"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <span>My Complaints</span>
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-bold text-primary">
            {myComplaints.length}
          </span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("review")}
          className={`flex items-center gap-2 border-b-2 px-5 py-3 text-xs font-semibold transition-colors ${
            activeTab === "review"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          <span>Recents (7-Day Review)</span>
          {reviewAwaiting.length > 0 ? (
            <span className="rounded-full bg-warning/20 px-2 py-0.5 text-[10px] font-bold text-warning animate-pulse">
              {reviewAwaiting.length} pending
            </span>
          ) : (
            <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-bold text-muted-foreground">
              {reviewTabRows.length}
            </span>
          )}
        </button>
      </div>

      {/* If in Recents (7-Day Review) tab, display 7-day review action section */}
      {activeTab === "review" ? (
        <div className="space-y-6">
          <div className="rounded-lg border border-warning/30 bg-warning-soft p-5">
            <div className="flex items-start gap-3">
              <Clock3 className="mt-0.5 size-5 shrink-0 text-warning" />
              <div>
                <h3 className="text-sm font-bold text-warning-foreground">
                  7-Day Citizen Resolution Review Window
                </h3>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  Whenever a department officer finishes remediation on a complaint, it enters a <strong>7-day citizen review window</strong>. As a citizen, you can inspect the location and choose to either <strong>Confirm Satisfaction</strong> (which formally closes the case) or <strong>Object & Reopen Case</strong> if the problem is still unresolved.
                </p>
              </div>
            </div>
          </div>

          {/* Pending Reviews First */}
          {reviewAwaiting.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-wider text-warning">
                  Pending Your Review ({reviewAwaiting.length})
                </h3>
                <span className="text-[10px] text-muted-foreground">
                  Review before the 7-day deadline expires
                </span>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
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
                      className="rounded-lg border-2 border-warning/30 bg-surface p-5 shadow-xs flex flex-col justify-between"
                    >
                      <div>
                        <div className="flex items-center justify-between gap-2 mb-2">
                          <span className="text-xs font-bold text-primary">{row.id}</span>
                          <span className="rounded-full bg-warning/20 px-2.5 py-0.5 text-[10px] font-bold text-warning">
                            ⏱ {daysLeft} {daysLeft === 1 ? "day" : "days"} remaining
                          </span>
                        </div>
                        <Link
                          to="/complaints/$id"
                          params={{ id: row.id }}
                          className="text-base font-bold text-foreground hover:text-primary hover:underline"
                        >
                          {row.title}
                        </Link>
                        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                          <strong>Officer Remediation Note:</strong>{" "}
                          {row.resolution?.notes || "Remediation submitted by department officer for citizen review."}
                        </p>
                        <div className="mt-2 text-[11px] text-muted-foreground">
                          <strong>Department:</strong> {row.department} · {row.ward}
                        </div>
                        {row.resolution?.evidence && row.resolution.evidence.length > 0 && (
                          <div className="mt-3">
                            <span className="text-[10px] font-semibold text-muted-foreground uppercase">
                              Officer Site Photos:
                            </span>
                            <div className="mt-1 flex gap-2 overflow-x-auto">
                              {row.resolution.evidence.map((photo, i) => (
                                <img
                                  key={i}
                                  src={photo}
                                  alt="Remediation evidence"
                                  className="size-16 rounded object-cover border border-border"
                                />
                              ))}
                            </div>
                          </div>
                        )}
                      </div>

                      <div className="mt-5 pt-4 border-t border-border flex flex-wrap items-center justify-between gap-2">
                        <Link
                          to="/complaints/$id"
                          params={{ id: row.id }}
                          className="text-xs font-medium text-primary hover:underline flex items-center gap-1"
                        >
                          View Full Event & Remarks &rarr;
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
                            Object / Reopen
                          </Button>
                          <Button
                            size="sm"
                            className="h-8 px-3 text-xs bg-success hover:bg-success/90 text-success-foreground font-semibold"
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

          {/* Solved / Closed Complaints */}
          <section className="space-y-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Solved & Citizen-Verified Complaints ({recentlySolved.length})
            </h3>
            <div className="panel divide-y divide-border">
              {recentlySolved.map((row) => (
                <div key={row.id} className="p-4 hover:bg-muted/30 transition-colors">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex items-start gap-3 min-w-0">
                      <div
                        className="mt-1 size-3 rounded-full shrink-0"
                        style={{ backgroundColor: getDepartmentColor(row.department) }}
                      />
                      <div>
                        <Link
                          to="/complaints/$id"
                          params={{ id: row.id }}
                          className="text-xs font-bold text-foreground hover:text-primary"
                        >
                          {row.title}
                        </Link>
                        <p className="mt-1 text-xs text-muted-foreground line-clamp-1">
                          {row.description}
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                          <span className="font-semibold text-foreground">{row.id}</span>
                          <span>·</span>
                          <span>{row.department}</span>
                          <span>·</span>
                          <span>{row.ward}</span>
                          <span>·</span>
                          <span className="text-success font-semibold flex items-center gap-1">
                            <CheckCheck className="size-3" />
                            Satisfaction Confirmed & Closed
                          </span>
                        </div>
                      </div>
                    </div>
                    <Button asChild size="sm" variant="ghost" className="h-8 text-xs shrink-0">
                      <Link to="/complaints/$id" params={{ id: row.id }}>
                        Full Event Remarks &rarr;
                      </Link>
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      ) : (
        <>
          {/* Filters for All Complaints and My Complaints */}
          <div className="mb-5 flex flex-wrap gap-3">
            <div className="relative min-w-52 flex-1">
              <Search className="absolute left-3 top-3.5 size-4 text-muted-foreground" />
              <input
                className="form-field pl-10"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search by title, tracking ID, department, or location..."
                aria-label={t("search")}
              />
            </div>

            <select
              className="form-field w-auto"
              aria-label="Filter by department"
              value={department}
              onChange={(event) => setDepartment(event.target.value)}
            >
              <option value="all">All Departments</option>
              {allDepts.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>

            <select
              className="form-field w-auto"
              aria-label="Filter by status"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="all">{t("allStatuses")}</option>
              {["submitted", "in_progress", "review", "resolved", "challenged", "reopened"].map(
                (value) => (
                  <option key={value} value={value}>
                    {t(value)}
                  </option>
                ),
              )}
            </select>
          </div>

          <section className="panel">
            {filtered.length === 0 ? (
              <div className="p-8 text-center text-xs text-muted-foreground">
                {activeTab === "mine"
                  ? "You have not submitted any complaints yet. Click 'New Report' above to report an issue in your area."
                  : "No complaints found matching your search filters."}
              </div>
            ) : (
              <ComplaintTable rows={filtered} />
            )}
          </section>
        </>
      )}

      {/* Modal Dialog for Reopening Case */}
      <Dialog open={Boolean(reopenTarget)} onOpenChange={(open) => { if (!open) setReopenTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Object & Reopen Complaint</DialogTitle>
            <DialogDescription>
              Explain why the issue is still not solved or has re-occurred. Your objection will reopen the case and assign it to a department supervisor for independent review.
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
                <label htmlFor="complaints-reopen-input" className="block text-xs font-semibold mb-1.5">
                  Objection Reason & Notes
                </label>
                <textarea
                  id="complaints-reopen-input"
                  rows={4}
                  className="form-field text-xs resize-none"
                  placeholder="Detail why you are dissatisfied with the proposed remediation..."
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
export function TrackPage({ initialId = "" }: { initialId?: string }) {
  const { t } = useTranslation();
  const [input, setInput] = useState(initialId);
  const [searched, setSearched] = useState("");
  const [row, setRow] = useState<Complaint | null>(null);
  const [trackingError, setTrackingError] = useState("");
  const [tracking, setTracking] = useState(false);
  const track = useCallback(async (identifier: string) => {
    const normalized = identifier.trim();
    if (!normalized) return;
    setSearched(normalized);
    setTracking(true);
    setTrackingError("");
    setRow(null);
    try {
      setRow(await civicApi.track(normalized));
    } catch (failure) {
      setTrackingError(failure instanceof Error ? failure.message : "Tracking is unavailable.");
    } finally {
      setTracking(false);
    }
  }, []);
  useEffect(() => {
    if (initialId) void track(initialId);
  }, [initialId, track]);
  return (
    <div className="page-container fade-in">
      <PageHeading
        title={t("track")}
        subtitle="Follow official updates with your complaint tracking ID."
      />
      <div className="max-w-3xl">
        <form
          className="flex flex-wrap gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void track(input);
          }}
        >
          <label htmlFor="tracking-id" className="sr-only">
            Tracking ID
          </label>
          <input
            id="tracking-id"
            value={input}
            onChange={(event) => setInput(event.target.value.toUpperCase())}
            className="form-field min-w-52 flex-1"
            placeholder={t("trackingPlaceholder")}
            required
          />
          <Button className="h-11 px-6" type="submit">
            <Search />
            {t("trackingButton")}
          </Button>
        </form>
        {tracking && (
          <div className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" />
            Checking official status…
          </div>
        )}
        {searched &&
          !tracking &&
          (row ? (
            <section className="panel mt-6 p-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-xs font-medium text-primary">{row.id}</span>
                <StatusBadge status={row.status} verified={row.evidenceVerified} />
              </div>
              <h2 className="mt-4 text-xl font-bold">{row.title}</h2>
              <p className="mt-3 text-sm text-muted-foreground">{row.department}</p>
              <div className="mt-7">
                <Timeline row={row} />
              </div>
              {isDemo && (
                <Button asChild variant="outline">
                  <Link to="/complaints/$id" params={{ id: row.id }}>
                    View complaint
                    <ArrowRight />
                  </Link>
                </Button>
              )}
            </section>
          ) : (
            <div className="mt-6 rounded-md border border-border p-6">
              <AlertCircle className="mb-3 size-6 text-warning" />
              <h2 className="font-semibold">No report found</h2>
              <p className="mt-2 text-muted-foreground">
                {trackingError || "Check the tracking ID and try again."}
              </p>
            </div>
          ))}
      </div>
    </div>
  );
}
export function SubmitPage({ initialCategory }: { initialCategory?: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: rows } = useSuspenseQuery(complaintsQuery);
  const validCategory =
    categories.find((item) => item.name === initialCategory)?.name ?? "Roads & footpaths";
  const form = useForm<DescriptionForm>({
    resolver: zodResolver(schema),
    defaultValues: { title: "", description: "", category: validCategory },
  });
  const values = form.watch();
  const [step, setStep] = useState(0);
  const [address, setAddress] = useState("");
  const [coords, setCoords] = useState({ lat: 12.972, lng: 77.641 });
  const [photos, setPhotos] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [result, setResult] = useState<Complaint | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const key = useRef("");
  useEffect(() => {
    key.current = crypto.randomUUID();
    try {
      const draft = localStorage.getItem("civic-draft");
      if (draft) {
        const data = JSON.parse(draft) as {
          values: DescriptionForm;
          address: string;
          coords: { lat: number; lng: number };
        };
        form.reset(data.values);
        setAddress(data.address);
        setCoords(data.coords);
        setSaved(true);
      }
    } catch {
      /* A damaged draft should not stop a new report. */
    }
    setReady(true);
  }, [form]);
  useEffect(() => {
    if (!ready || result) return;
    const timeout = setTimeout(() => {
      try {
        localStorage.setItem("civic-draft", JSON.stringify({ values, address, coords }));
        setSaved(Boolean(values.title || values.description));
      } catch {
        setFailure(
          "Device storage is unavailable. Keep this page open until your report is submitted.",
        );
      }
    }, 500);
    return () => clearTimeout(timeout);
  }, [values.title, values.description, values.category, address, coords, ready, result]);
  const online = useOnline();
  const nearby = rows
    .filter((row) => row.category === values.category && !["resolved"].includes(row.status))
    .map((row) => ({ row, meters: distanceMeters(coords, row) }))
    .filter((item) => item.meters <= 500)
    .sort((a, b) => a.meters - b.meters)
    .slice(0, 3);
  const pick = useCallback((lat: number, lng: number) => setCoords({ lat, lng }), []);
  async function locate() {
    if (!navigator.geolocation)
      return void toast.error("Location services are not supported by this browser.");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        toast.success("Your location has been selected.");
      },
      () =>
        toast.error("Location access was denied. Select a point on the map or enter coordinates."),
    );
  }
  async function searchAddress() {
    if (address.trim().length < 4) return void toast.error("Enter a street or landmark.");
    setBusy(true);
    try {
      const response = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=in&q=${encodeURIComponent(address + ", Bengaluru")}`,
      );
      if (!response.ok)
        throw new Error("Address search is unavailable. Choose a map point instead.");
      const found = (await response.json()) as { lat: string; lon: string }[];
      const first = found[0];
      if (!first) throw new Error("Address not found. Choose a map point instead.");
      pick(Number(first.lat), Number(first.lon));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not find the address.");
    } finally {
      setBusy(false);
    }
  }
  async function submit() {
    setFailure("");
    setBusy(true);
    try {
      if (!navigator.onLine)
        throw new Error("You are offline. Your draft is saved; reconnect and retry.");
      const row = await civicApi.create(
        { ...form.getValues(), address, ...coords, attachments: photos, language: i18n.language },
        key.current,
      );
      setResult(row);
      queryClient.setQueryData(complaintsQuery.queryKey, (old: Complaint[] | undefined) => [
        row,
        ...(old ?? []),
      ]);
      localStorage.removeItem("civic-draft");
      try {
        const existingMy = JSON.parse(sessionStorage.getItem("civic_my_complaints") || "[]");
        sessionStorage.setItem("civic_my_complaints", JSON.stringify([row.id, ...existingMy]));
      } catch {
        // ignore
      }
      toast.success(isDemo ? "Demonstration complaint created." : "Complaint submitted.");
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "Submission failed. Please retry.");
    } finally {
      setBusy(false);
    }
  }
  if (result)
    return (
      <div className="page-container">
        <div className="mx-auto max-w-2xl py-8">
          <div className="mb-6 grid size-14 place-items-center rounded-full bg-success-soft text-success">
            <Check className="size-7" />
          </div>
          <PageHeading
            title={t("successTitle")}
            subtitle={
              isDemo
                ? "This is a sample submission. No report was sent to a municipal authority."
                : "Your report has been received by the municipal service."
            }
          />
          <div className="mb-6 border-y border-border py-6">
            <p className="section-label text-muted-foreground">TRACKING ID</p>
            <p className="mt-3 font-display text-2xl font-bold text-primary">{result.id}</p>
          </div>
          <Timeline row={result} />
          <Button asChild>
            <Link to="/complaints/$id" params={{ id: result.id }}>
              View complaint
              <ArrowRight />
            </Link>
          </Button>
        </div>
      </div>
    );
  const steps = ["description", "location", "photos", "reviewSubmit"];
  return (
    <div className="page-container fade-in">
      <PageHeading
        title={t("submit")}
        subtitle="A clear report helps the right department take action."
      />
      <div className="mb-8 flex max-w-4xl items-start justify-between gap-2">
        {steps.map((item, index) => (
          <div key={item} className="flex flex-1 items-center gap-2">
            <span
              className={`step-index ${index === step ? "current" : index < step ? "done" : ""}`}
            >
              {index < step ? <Check className="size-4" /> : index + 1}
            </span>
            <span
              className={`hidden text-xs sm:block ${index === step ? "font-semibold text-primary" : "text-muted-foreground"}`}
            >
              {t(item)}
            </span>
            {index < 3 && <span className="mx-3 hidden flex-1 border-t border-border sm:block" />}
          </div>
        ))}
      </div>
      {step < 2 && (
        <div className="mb-7 max-w-4xl">
          <PopularIssuesNearYou lat={coords.lat} lng={coords.lng} compact />
        </div>
      )}
      {!online && (
        <div
          role="status"
          className="mb-6 flex max-w-4xl items-center gap-3 rounded-md border border-warning/30 bg-warning-soft p-4 text-xs text-warning"
        >
          <AlertCircle className="size-4" />
          You are offline. Your draft is saved on this device and will be ready to submit when you
          reconnect.
        </div>
      )}
      {online && saved && step === 0 && (
        <div
          role="status"
          className="mb-6 flex max-w-4xl items-center justify-between gap-3 rounded-md border border-border bg-secondary p-4 text-xs"
        >
          <span className="flex items-center gap-2">
            <Save className="size-4" />A saved draft was recovered on this device.
          </span>
          <Button
            size="sm"
            variant="ghost"
            type="button"
            onClick={() => {
              localStorage.removeItem("civic-draft");
              form.reset({ title: "", description: "", category: validCategory });
              setAddress("");
              setSaved(false);
            }}
          >
            Discard draft
          </Button>
        </div>
      )}
      <div className="grid items-start gap-8 xl:grid-cols-[minmax(0,780px)_260px]">
        <section className="min-w-0">
          {step === 0 && (
            <form onSubmit={form.handleSubmit(() => setStep(1))} className="space-y-6">
              <h2 className="text-lg font-bold">{t("describeTitle")}</h2>
              <div>
                <label htmlFor="issue-title" className="mb-2 block text-xs font-semibold">
                  {t("issueTitle")} <span className="text-destructive">*</span>
                </label>
                <input
                  id="issue-title"
                  className="form-field"
                  placeholder="e.g. Broken pavement near the community park"
                  {...form.register("title")}
                />
                {form.formState.errors.title && (
                  <p className="mt-2 text-xs text-destructive" role="alert">
                    {form.formState.errors.title.message}
                  </p>
                )}
              </div>
              <div>
                <label htmlFor="issue-category" className="mb-2 block text-xs font-semibold">
                  {t("category")}
                </label>
                <select id="issue-category" className="form-field" {...form.register("category")}>
                  {categories.map((item) => (
                    <option key={item.name}>{item.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <label htmlFor="issue-description" className="text-xs font-semibold">
                    {t("issueDescription")} <span className="text-destructive">*</span>
                  </label>
                  <span className="text-[10px] text-muted-foreground">
                    English · हिन्दी · ಕನ್ನಡ
                  </span>
                </div>
                <textarea
                  id="issue-description"
                  className="form-field min-h-44"
                  placeholder="Describe what happened, where it is, and how it affects your neighbourhood."
                  {...form.register("description")}
                />
                {form.formState.errors.description && (
                  <p className="mt-2 text-xs text-destructive" role="alert">
                    {form.formState.errors.description.message}
                  </p>
                )}
              </div>
              <VoiceInput
                onText={(text) =>
                  form.setValue("description", `${form.getValues("description")} ${text}`.trim())
                }
                language={i18n.language}
              />
              <div className="flex justify-end border-t border-border pt-5">
                <Button type="submit" className="h-11">
                  {t("next")}
                  <ArrowRight />
                </Button>
              </div>
            </form>
          )}
          {step === 1 && (
            <div className="space-y-5">
              <h2 className="text-lg font-bold">Pinpoint the location</h2>
              <div>
                <label htmlFor="address" className="mb-2 block text-xs font-semibold">
                  {t("address")}
                </label>
                <div className="flex gap-2">
                  <input
                    id="address"
                    className="form-field"
                    value={address}
                    onChange={(event) => setAddress(event.target.value)}
                    placeholder="Street, landmark, locality"
                  />
                  <Button
                    variant="outline"
                    className="h-11 min-w-11"
                    size="icon"
                    onClick={searchAddress}
                    disabled={busy}
                    aria-label="Search address"
                  >
                    <Search />
                  </Button>
                </div>
              </div>
              <div className="panel">
                <LocationMap lat={coords.lat} lng={coords.lng} onPick={pick} large />
              </div>
              <div className="flex flex-wrap items-center justify-between gap-4">
                <Button variant="outline" onClick={locate}>
                  <MapPin />
                  {t("useLocation")}
                </Button>
                <div className="flex gap-3">
                  {(["lat", "lng"] as const).map((axis) => (
                    <label key={axis} className="text-[10px] text-muted-foreground">
                      {axis === "lat" ? "Latitude" : "Longitude"}
                      <input
                        className="form-field mt-1 w-28 text-xs"
                        type="number"
                        step="0.0001"
                        min={axis === "lat" ? -90 : -180}
                        max={axis === "lat" ? 90 : 180}
                        value={coords[axis]}
                        onChange={(event) =>
                          setCoords((old) => ({ ...old, [axis]: Number(event.target.value) }))
                        }
                      />
                    </label>
                  ))}
                </div>
              </div>
              {!dismissed && values.description && (
                <div className="border-t border-border pt-4">
                  <h3 className="text-sm font-semibold">Possible similar reports nearby</h3>
                  <p className="mt-2 text-xs text-muted-foreground">
                    Same category within 500 m of your pin · Not a confirmed duplicate
                  </p>
                  {nearby.length === 0 && (
                    <p className="mt-3 text-xs text-muted-foreground">
                      No similar reports found near this location.
                    </p>
                  )}
                  {nearby.map(({ row, meters }) => (
                    <div key={row.id} className="mt-3 rounded-md border border-border p-4">
                      <p className="text-sm font-medium">{row.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {row.address} · {Math.round(meters)} m away
                      </p>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={async () => {
                            if (!isDemo) {
                              toast.error(
                                "Related-report matching is waiting for the API contract.",
                              );
                              return;
                            }
                            await civicApi.update(row.id, {}, "support");
                            toast.success("Support added to the sample report.");
                            await navigate({ to: "/complaints/$id", params: { id: row.id } });
                          }}
                        >
                          This is the same issue
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setDismissed(true)}>
                          This is different
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {step === 2 && (
            <div>
              <h2 className="mb-2 text-lg font-bold">Add supporting photos</h2>
              <p className="mb-6 text-xs text-muted-foreground">
                Optional · Up to 5 photos · JPG, PNG or WebP · 5 MB each
              </p>
              <label
                htmlFor="complaint-photos"
                className="flex min-h-44 cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-input bg-surface text-muted-foreground"
              >
                <Upload className="size-7 text-primary" />
                <span className="text-sm font-medium">{t("upload")}</span>
                <span className="text-xs">Avoid faces and personal documents.</span>
                <input
                  id="complaint-photos"
                  type="file"
                  multiple
                  accept="image/jpeg,image/png,image/webp"
                  className="sr-only"
                  onChange={async (event) => {
                    try {
                      const next = await readPhotos(event.target.files);
                      if (photos.length + next.length > 5)
                        throw new Error("Choose up to 5 photos.");
                      setPhotos((old) => [...old, ...next]);
                    } catch (error) {
                      toast.error(error instanceof Error ? error.message : "Upload failed.");
                    }
                  }}
                />
              </label>
              <PhotoGrid
                photos={photos}
                onRemove={(index) => setPhotos((old) => old.filter((_, i) => i !== index))}
              />
            </div>
          )}
          {step === 3 && (
            <div className="space-y-6">
              <h2 className="text-lg font-bold">Review your complaint</h2>
              <div className="border-y border-border py-5">
                <span className="status-pill status-neutral">
                  <CategoryIcon category={values.category} className="size-3" />
                  {values.category}
                </span>
                <h3 className="mt-4 text-xl font-bold">{values.title}</h3>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                  {values.description}
                </p>
                <p className="mt-5 flex items-center gap-2 text-xs">
                  <MapPin className="size-4 text-primary" />
                  {address}
                </p>
              </div>
              <PhotoGrid photos={photos} />
              <div className="flex items-start gap-3 rounded-md bg-secondary p-4">
                <ShieldCheck className="size-5 shrink-0 text-primary" />
                <p className="text-xs leading-relaxed text-muted-foreground">
                  A human officer reviews your complaint and confirms department assignment. AI
                  recommendations are not official findings.
                </p>
              </div>
              {isDemo && (
                <p className="text-xs text-warning">
                  Demonstration only: this report will not be sent to the government.
                </p>
              )}
            </div>
          )}
          {failure && (
            <div
              className="mt-5 flex items-start gap-3 rounded-md border border-destructive/20 bg-destructive/5 p-4 text-destructive"
              role="alert"
            >
              <AlertCircle className="size-5 shrink-0" />
              <p className="text-sm">{failure}</p>
            </div>
          )}
          {step > 0 && (
            <div className="mt-7 flex justify-between border-t border-border pt-5">
              <Button variant="outline" onClick={() => setStep((old) => old - 1)} disabled={busy}>
                <ArrowLeft />
                {t("back")}
              </Button>
              {step < 3 ? (
                <Button
                  className="h-11"
                  onClick={() => {
                    if (step === 1 && address.trim().length < 5) {
                      toast.error("Please enter the address or landmark.");
                      return;
                    }
                    setStep((old) => old + 1);
                  }}
                >
                  {t("next")}
                  <ArrowRight />
                </Button>
              ) : (
                <Button className="h-11" disabled={busy} onClick={submit}>
                  {busy ? <LoaderCircle className="animate-spin" /> : <FileCheck2 />}
                  {busy ? "Submitting…" : t("submitReport")}
                </Button>
              )}
            </div>
          )}
          {saved && (
            <p className="mt-5 flex items-center gap-2 text-[11px] text-muted-foreground">
              <Save className="size-3.5 text-primary" />
              {t("draftSaved")}
              <span>· Photos stay only while this page is open</span>
            </p>
          )}
        </section>
        <aside className="hidden border-l border-border pl-7 xl:block">
          <ShieldCheck className="mb-3 size-6 text-primary" />
          <h3 className="text-sm font-bold">Your report matters</h3>
          <p className="mt-3 text-xs leading-6 text-muted-foreground">
            Include a precise location and describe the problem clearly. Do not share personal
            identification numbers or sensitive information.
          </p>
          <div className="mt-6 border-t border-border pt-5">
            <h3 className="text-xs font-semibold">One accountable department</h3>
            <p className="mt-2 text-xs leading-6 text-muted-foreground">
              You can track the assigned department and official updates after submission.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
function PhotoGrid({ photos, onRemove }: { photos: string[]; onRemove?: (index: number) => void }) {
  return (
    <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
      {photos.map((photo, index) => (
        <div
          className="relative aspect-[4/3] overflow-hidden rounded-md border border-border"
          key={`${index}-${photo.slice(-15)}`}
        >
          <img
            src={photo}
            alt={`Supporting evidence ${index + 1}`}
            className="size-full object-cover"
          />
          {onRemove && (
            <Button
              size="icon"
              variant="secondary"
              className="absolute right-1 top-1"
              aria-label={`Remove photo ${index + 1}`}
              onClick={() => onRemove(index)}
            >
              <X />
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}
export function Timeline({ row, internal = false }: { row: Complaint; internal?: boolean }) {
  const { t } = useTranslation();
  return (
    <div>
      <h2 className="mb-5 text-sm font-bold">{t("timeline")}</h2>
      <ol className="timeline-line">
        {row.activity
          .filter((item) => internal || item.public)
          .map((item, index) => (
            <li className="timeline-item" key={`${item.date}-${index}`}>
              <span className="timeline-dot" />
              <p className="text-xs font-semibold">{item.title}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{item.note}</p>
              <p className="mt-2 text-[10px] text-muted-foreground">
                {item.department} · {item.date}
                {!item.public ? " · Internal only" : ""}
              </p>
            </li>
          ))}
      </ol>
    </div>
  );
}
export function ComplaintDetail({ id }: { id: string }) {
  const { data: rows } = useSuspenseQuery(complaintsQuery);
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const row = rows.find((item) => item.id === id);
  const [translated, setTranslated] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  if (!row)
    return (
      <div className="page-container">
        <PageHeading title="Complaint not found" />
        <Button asChild variant="outline">
          <Link to="/track">Track a complaint</Link>
        </Button>
      </div>
    );
  async function challenge() {
    if (!row || reason.trim().length < 10) return;
    setBusy(true);
    try {
      await civicApi.update(
        row.id,
        { status: "challenged", challenge: { reason, evidence } },
        "challenge",
      );
      await queryClient.invalidateQueries({ queryKey: ["complaints"] });
      setReviewOpen(false);
      toast.success("Challenge submitted for independent review.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not submit challenge.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-container fade-in">
      <Link to="/complaints" className="mb-5 flex items-center gap-2 text-xs text-muted-foreground">
        <ArrowLeft className="size-3.5" />
        {t("myComplaints")}
      </Link>
      <PageHeading
        title={row.title}
        subtitle={`${row.id} · Reported ${row.date}`}
        action={<StatusBadge status={row.status} verified={row.evidenceVerified} />}
      />
      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div>
          <div className="mb-7 flex flex-wrap items-center gap-3 border-y border-border py-5">
            <CategoryIcon category={row.category} />
            <span className="text-xs font-medium">{row.category}</span>
            <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
              <MapPin className="size-4" />
              {row.address}
            </span>
          </div>
          <div className="mb-8">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-bold">Original complaint</h2>
              <Button size="sm" variant="ghost" onClick={() => setTranslated((old) => !old)}>
                {t(translated ? "original" : "translated")}
              </Button>
            </div>
            <p className="text-sm leading-7 text-muted-foreground">
              {translated && row.language !== "en"
                ? "A verified translation is not available yet. The original complaint is shown below. "
                : ""}
              {row.description}
            </p>
          </div>
          <div className="mb-8">
            <h2 className="text-sm font-bold">{t("attachments")}</h2>
            {row.attachments.length ? (
              <PhotoGrid photos={row.attachments} />
            ) : (
              <p className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                <Image className="size-4" />
                {t("noAttachments")}
              </p>
            )}
          </div>
          {/* 7-DAY REVIEW WINDOW: Active if status is 'review' or resolution is present */}
          {(row.status === "review" || row.resolution) && row.status !== "resolved" && row.status !== "challenged" && row.status !== "reopened" && (
            <section className="mb-8 rounded-lg border-2 border-warning/40 bg-warning-soft px-5 py-6">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="flex items-center gap-2 text-sm font-bold text-warning">
                  <ClipboardCheck className="size-5" />
                  7-Day Citizen Resolution Review Window Active
                </h2>
                <span className="rounded-full bg-warning/20 px-2.5 py-0.5 text-[10px] font-bold text-warning">
                  ⏱{" "}
                  {Math.max(
                    0,
                    Math.ceil(
                      (new Date(row.resolution?.deadline || Date.now() + 7 * 86400000).getTime() -
                        Date.now()) /
                        86400000,
                    ),
                  )}{" "}
                  days remaining
                </span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                The municipal team has completed physical work on this complaint. You have up to 7 days to inspect the site and confirm your satisfaction, or object to reopen the case.
              </p>

              <div className="mt-4 rounded-md bg-surface p-4 border border-border">
                <h3 className="text-xs font-semibold text-foreground">Officer Remediation Remarks</h3>
                <p className="mt-1 text-sm leading-relaxed text-foreground">
                  {row.resolution?.notes || "Remediation works submitted for citizen approval."}
                </p>
                <p className="mt-2 text-[11px] text-muted-foreground">
                  Submitted by {row.resolution?.officer || "Field Duty Officer"} · {row.department}
                </p>

                {row.resolution?.evidence && row.resolution.evidence.length > 0 ? (
                  <div className="mt-4">
                    <h4 className="text-xs font-semibold text-muted-foreground">Officer Evidence Photos</h4>
                    <PhotoGrid photos={row.resolution.evidence} />
                  </div>
                ) : (
                  <p className="mt-2 text-[11px] text-muted-foreground italic">
                    No officer photos attached with this submission.
                  </p>
                )}
              </div>

              <div className="mt-5 flex flex-wrap items-center gap-3">
                <Button
                  disabled={busy}
                  className="bg-success hover:bg-success/90 text-success-foreground font-semibold"
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await civicApi.update(row.id, { note: "Citizen verified satisfaction with resolution." }, "confirm");
                      toast.success("You confirmed satisfaction! The complaint is now verified and closed.");
                      await queryClient.invalidateQueries({ queryKey: ["complaints"] });
                    } catch (error) {
                      toast.error(error instanceof Error ? error.message : "Confirmation failed.");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <Check className="size-4 mr-1.5" />
                  Confirm Satisfaction & Close Case
                </Button>
                <Button
                  variant="outline"
                  className="text-destructive hover:bg-destructive/10 border-destructive/30"
                  onClick={() => setReviewOpen(true)}
                  disabled={busy}
                >
                  <RotateCcw className="size-4 mr-1.5" />
                  Object & Reopen Case
                </Button>
              </div>
            </section>
          )}

          {/* RESOLVED STATUS BANNER */}
          {row.status === "resolved" && (
            <section className="mb-8 rounded-lg border border-success/30 bg-success-soft p-5">
              <div className="flex items-center gap-2 text-success">
                <CheckCheck className="size-5" />
                <h3 className="text-sm font-bold">Citizen Satisfaction Confirmed · Case Closed</h3>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                This grievance has been physically resolved by <strong>{row.department}</strong> and verified satisfactory within the 7-day citizen review window.
              </p>
              {row.resolution?.notes && (
                <p className="mt-2 text-xs text-foreground font-medium">
                  <strong>Final Resolution Remarks:</strong> {row.resolution.notes}
                </p>
              )}
            </section>
          )}

          {/* REOPENED / CHALLENGED STATUS BANNER */}
          {(row.status === "challenged" || row.status === "reopened") && (
            <section className="mb-8 rounded-lg border border-warning/40 bg-warning-soft p-5">
              <div className="flex items-center gap-2 text-warning">
                <RotateCcw className="size-5" />
                <h3 className="text-sm font-bold">Case Reopened by Citizen Objection</h3>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                The citizen reported that the problem was not satisfactorily solved. This case has been escalated to department supervisors for site re-inspection.
              </p>
              {row.challenge?.reason && (
                <div className="mt-3 rounded bg-surface p-3 border border-border text-xs">
                  <span className="font-semibold text-foreground">Citizen Objection:</span>
                  <p className="mt-1 text-muted-foreground">{row.challenge.reason}</p>
                </div>
              )}
            </section>
          )}

          <Timeline row={row} />
        </div>
        <aside>
          <section className="panel mb-5 p-5">
            <div className="flex items-center gap-2 text-primary">
              <ShieldCheck className="size-5" />
              <span className="text-[10px] font-semibold uppercase tracking-[1px]">
                Accountable Department
              </span>
            </div>
            <h2 className="mt-4 text-base font-bold">{row.department}</h2>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              This municipal department is responsible for remediating and coordinating this complaint.
            </p>
            <div className="mt-4 border-t border-border pt-4 text-xs text-muted-foreground">
              {row.ward}
            </div>

            {/* SLA Tracker */}
            {row.slaDeadline && (
              <div className="mt-4 rounded-md border border-border bg-secondary/50 p-3 text-xs">
                <span className="font-semibold text-foreground">SLA Target:</span>
                <p className="mt-1 text-muted-foreground">
                  {new Date(row.slaDeadline).toLocaleDateString("en-GB", {
                    day: "2-digit",
                    month: "short",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
                {row.slaOverdue ? (
                  <span className="mt-1 inline-block rounded bg-destructive/15 px-2 py-0.5 text-[10px] font-bold text-destructive">
                    SLA OVERDUE · Escalated
                  </span>
                ) : row.slaSecondsRemaining !== undefined ? (
                  <span className="mt-1 inline-block rounded bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                    ⏱ {Math.max(0, Math.floor(row.slaSecondsRemaining / 3600))} hours remaining
                  </span>
                ) : null}
              </div>
            )}
          </section>
          <section className="panel mt-5">
            <div className="p-4 text-xs font-semibold">Incident Location</div>
            <LocationMap lat={row.lat} lng={row.lng} />
            <p className="p-4 text-xs text-muted-foreground">{row.address}</p>
          </section>
        </aside>
      </div>
      <Dialog open={reviewOpen} onOpenChange={setReviewOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Challenge proposed resolution</DialogTitle>
            <DialogDescription>
              Your concern will be reviewed by an independent officer.
            </DialogDescription>
          </DialogHeader>
          <label htmlFor="challenge-reason" className="text-xs font-semibold">
            {t("reason")}
          </label>
          <textarea
            id="challenge-reason"
            className="form-field min-h-28"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Explain why the issue has not been resolved."
          />
          <label htmlFor="challenge-evidence" className="text-xs font-semibold">
            Supporting photos (optional)
          </label>
          <input
            id="challenge-evidence"
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp"
            onChange={async (event) => {
              try {
                setEvidence(await readPhotos(event.target.files));
              } catch (error) {
                toast.error(error instanceof Error ? error.message : "Invalid photos.");
              }
            }}
          />
          <Button disabled={reason.trim().length < 10 || busy} onClick={challenge}>
            Submit challenge
            <ArrowRight />
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
interface SpeechResultEvent {
  results: { [index: number]: { [index: number]: { transcript: string } } };
}
interface BrowserSpeech {
  lang: string;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}
function VoiceInput({ onText, language }: { onText: (text: string) => void; language: string }) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  useEffect(() => {
    setSupported("SpeechRecognition" in window || "webkitSpeechRecognition" in window);
  }, []);
  if (!supported) return null;
  return (
    <Button
      variant="outline"
      type="button"
      disabled={listening}
      onClick={() => {
        const browser = window as unknown as {
          SpeechRecognition?: new () => BrowserSpeech;
          webkitSpeechRecognition?: new () => BrowserSpeech;
        };
        const Recognition = browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
        if (!Recognition) return;
        const recognition = new Recognition();
        recognition.lang = language === "kn" ? "kn-IN" : language === "hi" ? "hi-IN" : "en-IN";
        recognition.onresult = (event) => {
          const transcript = event.results[0]?.[0]?.transcript;
          if (transcript) onText(transcript);
        };
        recognition.onerror = () => {
          toast.error("Voice input is unavailable. Please type your report.");
          setListening(false);
        };
        recognition.onend = () => setListening(false);
        recognition.start();
        setListening(true);
      }}
    >
      <Mic />
      {listening ? "Listening…" : "Use voice input"}
    </Button>
  );
}
export function SignInPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  return (
    <div className="page-container">
      <div className="mx-auto max-w-sm py-10">
        <ShieldCheck className="mb-5 size-10 text-primary" />
        <PageHeading
          title={t("signIn")}
          subtitle="Secure access to your municipal service account."
        />
        <div className="mb-4 mt-6">
          <p className="mb-2 text-[11px] font-semibold text-muted-foreground">Quick demo credentials:</p>
          <div className="flex flex-wrap gap-1.5">
            {[
              { label: "Citizen", email: "citizen@example.com", pass: "CitizenDemo123!" },
              { label: "Officer", email: "officer@example.com", pass: "OfficerDemo123!" },
              { label: "Lead", email: "lead@example.com", pass: "LeadDemo123!" },
              { label: "Supervisor", email: "supervisor@example.com", pass: "SupervisorDemo123!" },
              { label: "Admin", email: "admin@example.com", pass: "AdminDemo123!" },
              { label: "Auditor", email: "auditor@example.com", pass: "AuditorDemo123!" },
            ].map((acc) => (
              <button
                key={acc.label}
                type="button"
                className="rounded border border-border bg-secondary px-2.5 py-1 text-[11px] font-medium transition hover:bg-primary hover:text-primary-foreground"
                onClick={() => {
                  setEmail(acc.email);
                  setPassword(acc.pass);
                }}
              >
                {acc.label}
              </button>
            ))}
          </div>
        </div>
        <form
          className="space-y-5"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            try {
              const session = await request<Tokens>("/auth/login", {
                method: "POST",
                body: JSON.stringify({ email, password }),
              });
              setTokens(session);
              setDemoMode(false);
              await queryClient.invalidateQueries({ queryKey: ["complaints"] });
              const role = getSession()?.role ?? "citizen";
              await navigate(
                role === "citizen"
                  ? { to: "/" }
                  : { to: "/staff/$view", params: { view: "dashboard" } },
              );
              toast.success("Signed in successfully.");
            } catch (failure) {
              setError(failure instanceof Error ? failure.message : "Sign-in failed.");
            } finally {
              setBusy(false);
            }
          }}
        >
          <div>
            <label htmlFor="email" className="mb-2 block text-xs font-semibold">
              Email address
            </label>
            <input
              id="email"
              type="email"
              className="form-field"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-2 block text-xs font-semibold">
              Password
            </label>
            <input
              id="password"
              type="password"
              className="form-field"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>
          {error && (
            <p className="text-xs leading-relaxed text-destructive" role="alert">
              {error}
            </p>
          )}
          <Button className="h-11 w-full" disabled={busy} type="submit">
            {t("signIn")}
            <ArrowRight />
          </Button>
        </form>
      </div>
    </div>
  );
}
export function SupportPage({ section = "support" }: { section?: string }) {
  const { t } = useTranslation();
  return (
    <div className="page-container">
      <PageHeading title={t(section)} subtitle="CivicSense municipal grievance workspace" />
      <div className="max-w-2xl space-y-6 border-t border-border pt-6">
        {section === "privacy" ? (
          <>
            <h2 className="text-lg font-bold">Your information</h2>
            <p className="text-sm leading-7 text-muted-foreground">
              The demonstration uses sample records. Complaint drafts are saved on your device, and
              photo previews stay in your current session. Do not include sensitive personal
              information in a report. No municipal authority receives demonstration submissions.
            </p>
            <Button
              variant="outline"
              onClick={() => {
                localStorage.removeItem("civic-draft");
                toast.success("Local complaint draft deleted.");
              }}
            >
              Delete local draft
            </Button>
          </>
        ) : section === "accessibility" ? (
          <>
            <h2 className="text-lg font-bold">Accessible citizen services</h2>
            <p className="text-sm leading-7 text-muted-foreground">
              Location can be entered using coordinates instead of the map. Voice input is available
              in supported browsers. You can select English, Hindi or Kannada from the language
              menu.
            </p>
          </>
        ) : (
          <>
            <h2 className="text-lg font-bold">Complaint assistance</h2>
            <p className="text-sm leading-7 text-muted-foreground">
              Use your tracking ID to check your report. If a proposed resolution does not address
              the issue, open your complaint and submit a challenge for independent review.
            </p>
            <p className="text-sm leading-7 text-muted-foreground">
              Official municipal contact information has not been configured. This demonstration is
              not an emergency service; contact your local emergency service for immediate danger.
            </p>
            <div className="flex gap-3">
              <Button asChild>
                <Link to="/track">
                  Track a complaint
                  <ArrowRight />
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link to="/report">Report an issue</Link>
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
